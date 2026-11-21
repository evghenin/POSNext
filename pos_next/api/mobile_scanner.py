# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Whitelisted APIs for POSNext Mobile Scanner pairing, session, and command journal.

See docs/backend-pairing-design.md (project store) and the fork audit for design notes.

Security invariants:
- Pairing binds to a POS *session instance* (tab), not only POS Profile.
- Callers cannot invent company/warehouse/user — those come from the registered session.
- PIN is one-time + short TTL; after redeem a separate link_token is issued.
- Commands are idempotent on operation_id; same-id different payload is rejected.
- Server accept ≠ applied: POS must ACK via ack_command.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, cstr, get_datetime, now_datetime

from pos_next.mobile_scanner import audit
from pos_next.mobile_scanner.constants import (
	ACK_STATUSES,
	CHALLENGE_DOCTYPE,
	CHALLENGE_EXPIRED,
	CHALLENGE_OPEN,
	CHALLENGE_REDEEMED,
	CHALLENGE_REVOKED,
	CMD_ADD_ITEM,
	COMMAND_DOCTYPE,
	COMMAND_TYPES,
	DEVICE_CONNECTED,
	DEVICE_DISCONNECTED,
	DEVICE_DOCTYPE,
	DEVICE_REVOKED,
	HEARTBEAT_STALE_SECONDS,
	LINK_TOKEN_TTL_SECONDS,
	PAIRING_MAX_ATTEMPTS,
	PAIRING_PIN_LENGTH,
	PAIRING_TTL_SECONDS,
	SESSION_ACTIVE,
	SESSION_CLOSED,
	SESSION_DISCONNECTED,
	SESSION_DOCTYPE,
	STATUS_DELIVERED,
	STATUS_QUEUED,
)
from pos_next.mobile_scanner.crypto import (
	generate_pin,
	generate_token,
	generate_uuid,
	hash_secret,
	pin_alphabet_ok,
	secrets_equal,
)
from pos_next.mobile_scanner.payload import payload_hash, payloads_match
from pos_next.mobile_scanner.permissions import (
	assert_opening_shift,
	assert_pos_profile_access,
	assert_session_cashier,
	get_profile_context,
	require_cashier_or_manager,
	require_logged_in,
	require_mobile_scanner,
)
from pos_next.mobile_scanner.realtime import publish_command


def _pepper() -> str:
	"""Site-scoped pepper so stolen DB hashes are not reusable across sites."""
	try:
		return cstr(frappe.local.conf.get("encryption_key") or frappe.local.site or "posnext")
	except Exception:
		return "posnext"


def _hash(value: str) -> str:
	return hash_secret(value, pepper=_pepper())


def _parse_json(value: Any, field_name: str = "payload") -> Any:
	if value is None or value == "":
		return None
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		frappe.throw(_("Invalid JSON for {0}").format(field_name), frappe.ValidationError)


def _dump_json(value: Any) -> str:
	if value is None:
		return ""
	if isinstance(value, str):
		return value
	return json.dumps(value, default=str, sort_keys=True)


def _session_fields() -> list[str]:
	return [
		"name",
		"session_instance_id",
		"client_instance_id",
		"status",
		"pos_profile",
		"pos_opening_shift",
		"cashier_user",
		"company",
		"warehouse",
		"cart_generation",
		"payment_busy",
		"last_heartbeat",
		"cart_snapshot",
		"closed_at",
	]


def _get_session(session_instance_id: str, *, for_update: bool = False) -> dict:
	if not session_instance_id:
		frappe.throw(_("session_instance_id is required"), frappe.ValidationError)
	row = frappe.db.get_value(
		SESSION_DOCTYPE,
		{"session_instance_id": session_instance_id},
		_session_fields(),
		as_dict=True,
		for_update=for_update,
	)
	if not row:
		frappe.throw(_("POS mobile session not found"), frappe.DoesNotExistError)
	return row


def _session_is_reachable(session: dict) -> bool:
	if session.get("status") != SESSION_ACTIVE:
		return False
	last = session.get("last_heartbeat")
	if not last:
		return False
	age = now_datetime() - get_datetime(last)
	return age.total_seconds() <= HEARTBEAT_STALE_SECONDS


def _public_session(session: dict) -> dict:
	return {
		"session_instance_id": session.session_instance_id,
		"status": session.status,
		"pos_profile": session.pos_profile,
		"pos_opening_shift": session.pos_opening_shift,
		"company": session.company,
		"warehouse": session.warehouse,
		"cart_generation": session.cart_generation,
		"payment_busy": cint(session.payment_busy),
		"last_heartbeat": session.last_heartbeat,
		"reachable": _session_is_reachable(session),
	}


def _command_public(row: dict) -> dict:
	result = _parse_json(row.get("result_json"), "result_json") if row.get("result_json") else None
	payload = _parse_json(row.get("payload_json"), "payload_json") if row.get("payload_json") else None
	return {
		"operation_id": row.operation_id,
		"batch_id": row.batch_id,
		"command_type": row.command_type,
		"status": row.status,
		"session_instance_id": row.session_instance_id,
		"device_id": row.device_id,
		"cart_generation": row.cart_generation,
		"payload": payload,
		"result": result,
		"created_at_client": row.get("created_at_client"),
		"delivered_at": row.get("delivered_at"),
		"acked_at": row.get("acked_at"),
		"creation": row.get("creation"),
	}


# ---------------------------------------------------------------------------
# POS till: session registration + heartbeat + snapshot
# ---------------------------------------------------------------------------


@frappe.whitelist()
def register_session(
	client_instance_id: str,
	pos_profile: str,
	pos_opening_shift: str | None = None,
	cart_generation: str | None = None,
	session_instance_id: str | None = None,
):
	"""Register or resume a POS tab session instance.

	``client_instance_id`` should be persisted in sessionStorage so a reload can
	resume the same logical tab. If ``session_instance_id`` is provided and still
	owned by this cashier, it is resumed; otherwise a new UUID is minted.
	"""
	user = require_cashier_or_manager()
	client_instance_id = cstr(client_instance_id).strip()
	pos_profile = cstr(pos_profile).strip()
	if not client_instance_id:
		frappe.throw(_("client_instance_id is required"), frappe.ValidationError)

	assert_pos_profile_access(pos_profile, user)
	profile = get_profile_context(pos_profile)
	shift = assert_opening_shift(cstr(pos_opening_shift).strip() or None, pos_profile, user)

	company = profile.company
	if shift and shift.get("company"):
		company = shift.company

	now = now_datetime()
	cart_generation = cstr(cart_generation).strip() or generate_uuid()

	# Resume by explicit session id
	existing = None
	if session_instance_id:
		existing = frappe.db.get_value(
			SESSION_DOCTYPE,
			{"session_instance_id": cstr(session_instance_id).strip()},
			_session_fields(),
			as_dict=True,
			for_update=True,
		)
		if existing and existing.cashier_user != user and "System Manager" not in frappe.get_roles(user):
			existing = None

	# Or resume by client_instance_id for this cashier + profile
	if not existing:
		existing = frappe.db.get_value(
			SESSION_DOCTYPE,
			{
				"client_instance_id": client_instance_id,
				"cashier_user": user,
				"pos_profile": pos_profile,
				"status": ("in", [SESSION_ACTIVE, SESSION_DISCONNECTED]),
			},
			_session_fields(),
			as_dict=True,
			for_update=True,
		)

	if existing:
		doc = frappe.get_doc(SESSION_DOCTYPE, existing.name)
		doc.status = SESSION_ACTIVE
		doc.pos_opening_shift = (shift.name if shift else pos_opening_shift) or doc.pos_opening_shift
		doc.company = company
		doc.warehouse = profile.warehouse
		doc.last_heartbeat = now
		if cart_generation:
			doc.cart_generation = cart_generation
		doc.flags.ignore_permissions = True
		doc.save()
		audit.record(
			event_type="session_resumed",
			session_instance_id=doc.session_instance_id,
			pos_profile=pos_profile,
			user=user,
			details={"client_instance_id": client_instance_id},
		)
		return {
			"session_instance_id": doc.session_instance_id,
			"cart_generation": doc.cart_generation,
			"resumed": True,
			**_public_session(doc.as_dict()),
		}

	sid = generate_uuid()
	doc = frappe.get_doc(
		{
			"doctype": SESSION_DOCTYPE,
			"session_instance_id": sid,
			"client_instance_id": client_instance_id,
			"status": SESSION_ACTIVE,
			"pos_profile": pos_profile,
			"pos_opening_shift": shift.name if shift else (pos_opening_shift or ""),
			"cashier_user": user,
			"company": company,
			"warehouse": profile.warehouse,
			"cart_generation": cart_generation,
			"payment_busy": 0,
			"last_heartbeat": now,
			"cart_snapshot": _dump_json({"items": [], "cart_generation": cart_generation}),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()

	audit.record(
		event_type="session_registered",
		session_instance_id=sid,
		pos_profile=pos_profile,
		user=user,
		details={"client_instance_id": client_instance_id},
	)
	return {
		"session_instance_id": sid,
		"cart_generation": cart_generation,
		"resumed": False,
		**_public_session(doc.as_dict()),
	}


@frappe.whitelist()
def heartbeat(
	session_instance_id: str,
	cart_generation: str | None = None,
	cart_snapshot: str | dict | None = None,
	payment_busy: int | str | None = 0,
):
	"""POS till heartbeat. Optionally pushes cart snapshot + generation."""
	user = require_cashier_or_manager()
	session = _get_session(session_instance_id, for_update=True)
	assert_session_cashier(session, user)

	doc = frappe.get_doc(SESSION_DOCTYPE, session.name)
	doc.status = SESSION_ACTIVE
	doc.last_heartbeat = now_datetime()
	doc.payment_busy = 1 if cint(payment_busy) else 0
	if cart_generation is not None and cstr(cart_generation).strip():
		doc.cart_generation = cstr(cart_generation).strip()
	if cart_snapshot is not None:
		parsed = _parse_json(cart_snapshot, "cart_snapshot")
		if isinstance(parsed, dict):
			parsed.setdefault("cart_generation", doc.cart_generation)
			parsed.setdefault("payment_busy", cint(doc.payment_busy))
			parsed["updated_at"] = str(now_datetime())
			doc.cart_snapshot = _dump_json(parsed)
		else:
			frappe.throw(_("cart_snapshot must be a JSON object"), frappe.ValidationError)
	doc.flags.ignore_permissions = True
	doc.save()

	return {
		"ok": True,
		"session_instance_id": doc.session_instance_id,
		"cart_generation": doc.cart_generation,
		"payment_busy": cint(doc.payment_busy),
		"last_heartbeat": doc.last_heartbeat,
	}


@frappe.whitelist()
def update_cart_snapshot(
	session_instance_id: str,
	cart_generation: str,
	cart_snapshot: str | dict,
	payment_busy: int | str | None = 0,
):
	"""Explicit cart snapshot write (also accepted via heartbeat)."""
	return heartbeat(
		session_instance_id=session_instance_id,
		cart_generation=cart_generation,
		cart_snapshot=cart_snapshot,
		payment_busy=payment_busy,
	)


@frappe.whitelist()
def close_session(session_instance_id: str):
	"""Mark session closed (e.g. shift end / tab teardown). Revokes open challenges + devices."""
	user = require_cashier_or_manager()
	session = _get_session(session_instance_id, for_update=True)
	assert_session_cashier(session, user)

	now = now_datetime()
	doc = frappe.get_doc(SESSION_DOCTYPE, session.name)
	doc.status = SESSION_CLOSED
	doc.closed_at = now
	doc.flags.ignore_permissions = True
	doc.save()

	_revoke_open_challenges(session.session_instance_id)
	_disconnect_all_devices(session.session_instance_id, reason="session_closed")

	audit.record(
		event_type="session_closed",
		session_instance_id=session.session_instance_id,
		pos_profile=session.pos_profile,
		user=user,
	)
	return {"ok": True, "status": SESSION_CLOSED}


# ---------------------------------------------------------------------------
# POS till: pairing challenge
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_pairing_challenge(session_instance_id: str):
	"""Create a short-lived one-time PIN + QR token bound to this session instance.

	Returns plaintext PIN and qr_token once; only hashes are stored.
	"""
	user = require_cashier_or_manager()
	session = _get_session(session_instance_id)
	assert_session_cashier(session, user)
	if session.status == SESSION_CLOSED:
		frappe.throw(_("Session is closed"), frappe.ValidationError)

	# Revoke any still-open challenges for this session (one active challenge)
	_revoke_open_challenges(session.session_instance_id)

	pin = generate_pin(PAIRING_PIN_LENGTH)
	qr_token = generate_token(24)
	expires_at = now_datetime() + timedelta(seconds=PAIRING_TTL_SECONDS)

	doc = frappe.get_doc(
		{
			"doctype": CHALLENGE_DOCTYPE,
			"session_instance_id": session.session_instance_id,
			"status": CHALLENGE_OPEN,
			"pos_profile": session.pos_profile,
			"pos_opening_shift": session.pos_opening_shift,
			"created_by_user": user,
			"pin_hash": _hash(pin),
			"qr_token_hash": _hash(qr_token),
			"expires_at": expires_at,
			"max_attempts": PAIRING_MAX_ATTEMPTS,
			"attempt_count": 0,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()

	audit.record(
		event_type="pairing_challenge_created",
		session_instance_id=session.session_instance_id,
		pos_profile=session.pos_profile,
		user=user,
		details={"challenge": doc.name, "expires_at": str(expires_at)},
	)

	return {
		"challenge_id": doc.name,
		"pin": pin,
		"qr_token": qr_token,
		"expires_at": expires_at,
		"ttl_seconds": PAIRING_TTL_SECONDS,
		"session_instance_id": session.session_instance_id,
		"pos_profile": session.pos_profile,
	}


@frappe.whitelist()
def revoke_pairing_challenge(challenge_id: str):
	"""Revoke an open pairing challenge from the POS till."""
	user = require_cashier_or_manager()
	challenge_id = cstr(challenge_id).strip()
	doc = frappe.get_doc(CHALLENGE_DOCTYPE, challenge_id)
	session = _get_session(doc.session_instance_id)
	assert_session_cashier(session, user)

	if doc.status == CHALLENGE_OPEN:
		doc.status = CHALLENGE_REVOKED
		doc.flags.ignore_permissions = True
		doc.save()

	audit.record(
		event_type="pairing_challenge_revoked",
		session_instance_id=doc.session_instance_id,
		pos_profile=doc.pos_profile,
		user=user,
		details={"challenge": challenge_id},
	)
	return {"ok": True, "status": doc.status}


def _revoke_open_challenges(session_instance_id: str) -> None:
	names = frappe.get_all(
		CHALLENGE_DOCTYPE,
		filters={"session_instance_id": session_instance_id, "status": CHALLENGE_OPEN},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value(CHALLENGE_DOCTYPE, name, "status", CHALLENGE_REVOKED)


# ---------------------------------------------------------------------------
# Mobile: redeem pairing → link token
# ---------------------------------------------------------------------------


@frappe.whitelist()
def redeem_pairing(
	device_id: str,
	pin: str | None = None,
	qr_token: str | None = None,
	device_label: str | None = None,
	user_agent: str | None = None,
):
	"""Redeem a pairing PIN or QR token. Issues a time-limited link_token.

	Requires an authenticated ERPNext user with mobile scanner rights.
	The six-digit PIN does not replace login.
	"""
	user = require_mobile_scanner()
	device_id = cstr(device_id).strip()
	pin = cstr(pin).strip() if pin else ""
	qr_token = cstr(qr_token).strip() if qr_token else ""

	if not device_id:
		frappe.throw(_("device_id is required"), frappe.ValidationError)
	if not pin and not qr_token:
		frappe.throw(_("pin or qr_token is required"), frappe.ValidationError)
	if pin and not pin_alphabet_ok(pin, PAIRING_PIN_LENGTH):
		frappe.throw(_("PIN must be exactly {0} digits").format(PAIRING_PIN_LENGTH), frappe.ValidationError)

	challenge = _find_open_challenge(pin=pin, qr_token=qr_token)
	if not challenge:
		audit.record(
			event_type="pairing_failed",
			user=user,
			device_id=device_id,
			details={"reason": "not_found_or_invalid"},
		)
		frappe.throw(_("Invalid or expired pairing code"), frappe.ValidationError)

	doc = frappe.get_doc(CHALLENGE_DOCTYPE, challenge.name)
	# Lock row
	frappe.db.get_value(CHALLENGE_DOCTYPE, doc.name, "name", for_update=True)
	doc.reload()

	if doc.status != CHALLENGE_OPEN:
		frappe.throw(_("Pairing code is no longer valid"), frappe.ValidationError)

	if get_datetime(doc.expires_at) < now_datetime():
		doc.status = CHALLENGE_EXPIRED
		doc.flags.ignore_permissions = True
		doc.save()
		frappe.throw(_("Pairing code has expired"), frappe.ValidationError)

	if cint(doc.attempt_count) >= cint(doc.max_attempts):
		doc.status = CHALLENGE_REVOKED
		doc.flags.ignore_permissions = True
		doc.save()
		frappe.throw(_("Too many pairing attempts"), frappe.ValidationError)

	ok = False
	if pin and secrets_equal(doc.pin_hash, _hash(pin)):
		ok = True
	elif qr_token and secrets_equal(doc.qr_token_hash, _hash(qr_token)):
		ok = True

	if not ok:
		doc.attempt_count = cint(doc.attempt_count) + 1
		if cint(doc.attempt_count) >= cint(doc.max_attempts):
			doc.status = CHALLENGE_REVOKED
		doc.flags.ignore_permissions = True
		doc.save()
		audit.record(
			event_type="pairing_failed",
			session_instance_id=doc.session_instance_id,
			pos_profile=doc.pos_profile,
			user=user,
			device_id=device_id,
			details={"reason": "bad_secret", "attempts": doc.attempt_count},
		)
		frappe.throw(_("Invalid or expired pairing code"), frappe.ValidationError)

	session = _get_session(doc.session_instance_id)
	if session.status == SESSION_CLOSED:
		frappe.throw(_("POS session is closed"), frappe.ValidationError)

	# Mobile user may not invent till context — only bind to this session's profile.
	# Soft check: if they are restricted to profiles via POS Profile User, enforce it.
	# Floor scanners often are not on the profile user table; allow role-based access
	# but never let them pick a different profile than the challenge's.
	now = now_datetime()
	link_token = generate_token(32)
	link_expires = now + timedelta(seconds=LINK_TOKEN_TTL_SECONDS)

	# Disconnect prior connection for same device_id on this session
	_disconnect_device_rows(session.session_instance_id, device_id, reason="repaired")

	device = frappe.get_doc(
		{
			"doctype": DEVICE_DOCTYPE,
			"device_id": device_id,
			"session_instance_id": session.session_instance_id,
			"status": DEVICE_CONNECTED,
			"mobile_user": user,
			"pos_profile": session.pos_profile,
			"device_label": cstr(device_label).strip()[:140] or None,
			"link_token_hash": _hash(link_token),
			"link_token_expires_at": link_expires,
			"paired_at": now,
			"last_seen": now,
			"user_agent": cstr(user_agent).strip()[:500] or None,
		}
	)
	device.flags.ignore_permissions = True
	device.insert()

	doc.status = CHALLENGE_REDEEMED
	doc.redeemed_by = user
	doc.redeemed_at = now
	doc.redeemed_device_id = device_id
	doc.flags.ignore_permissions = True
	doc.save()

	audit.record(
		event_type="device_paired",
		session_instance_id=session.session_instance_id,
		pos_profile=session.pos_profile,
		user=user,
		device_id=device_id,
		details={"device": device.name, "link_expires_at": str(link_expires)},
	)

	publish_command(
		session.session_instance_id,
		{"type": "device_paired", "device_id": device_id, "mobile_user": user},
	)

	return {
		"link_token": link_token,
		"link_token_expires_at": link_expires,
		"device_id": device_id,
		"session": _public_session(session),
		"pos_profile": session.pos_profile,
		"company": session.company,
		"warehouse": session.warehouse,
	}


def _find_open_challenge(*, pin: str, qr_token: str) -> dict | None:
	"""Locate the open challenge matching PIN or QR hash.

	Open challenges are short-lived and few; we scan recent Open rows rather than
	indexing plaintext. PIN/QR are hashed with site pepper before compare.
	"""
	candidates = frappe.get_all(
		CHALLENGE_DOCTYPE,
		filters={"status": CHALLENGE_OPEN},
		fields=["name", "pin_hash", "qr_token_hash", "expires_at", "attempt_count", "max_attempts"],
		order_by="creation desc",
		limit_page_length=50,
	)
	pin_h = _hash(pin) if pin else None
	qr_h = _hash(qr_token) if qr_token else None
	now = now_datetime()
	for row in candidates:
		if get_datetime(row.expires_at) < now:
			continue
		if pin_h and secrets_equal(row.pin_hash, pin_h):
			return row
		if qr_h and secrets_equal(row.qr_token_hash, qr_h):
			return row
	return None


# ---------------------------------------------------------------------------
# Devices: list / disconnect
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_devices(session_instance_id: str):
	"""List devices connected to this POS session (POS till API)."""
	user = require_cashier_or_manager()
	session = _get_session(session_instance_id)
	assert_session_cashier(session, user)

	rows = frappe.get_all(
		DEVICE_DOCTYPE,
		filters={"session_instance_id": session.session_instance_id},
		fields=[
			"name",
			"device_id",
			"status",
			"mobile_user",
			"device_label",
			"paired_at",
			"last_seen",
			"disconnected_at",
			"link_token_expires_at",
		],
		order_by="paired_at desc",
	)
	return {"devices": rows, "session_instance_id": session.session_instance_id}


@frappe.whitelist()
def disconnect_device(session_instance_id: str, device_id: str):
	"""POS till disconnects a mobile device."""
	user = require_cashier_or_manager()
	session = _get_session(session_instance_id)
	assert_session_cashier(session, user)
	device_id = cstr(device_id).strip()
	_disconnect_device_rows(session.session_instance_id, device_id, reason="cashier_disconnect")
	audit.record(
		event_type="device_disconnected",
		session_instance_id=session.session_instance_id,
		pos_profile=session.pos_profile,
		user=user,
		device_id=device_id,
		details={"by": "cashier"},
	)
	publish_command(
		session.session_instance_id,
		{"type": "device_disconnected", "device_id": device_id},
	)
	return {"ok": True}


@frappe.whitelist()
def disconnect_self(link_token: str):
	"""Mobile device disconnects itself."""
	user = require_mobile_scanner()
	device, session = _resolve_link_token(link_token, touch=False)
	_disconnect_device_rows(session.session_instance_id, device.device_id, reason="self_disconnect")
	audit.record(
		event_type="device_disconnected",
		session_instance_id=session.session_instance_id,
		pos_profile=session.pos_profile,
		user=user,
		device_id=device.device_id,
		details={"by": "mobile"},
	)
	return {"ok": True}


def _disconnect_device_rows(session_instance_id: str, device_id: str, reason: str) -> None:
	names = frappe.get_all(
		DEVICE_DOCTYPE,
		filters={
			"session_instance_id": session_instance_id,
			"device_id": device_id,
			"status": DEVICE_CONNECTED,
		},
		pluck="name",
	)
	now = now_datetime()
	for name in names:
		frappe.db.set_value(
			DEVICE_DOCTYPE,
			name,
			{
				"status": DEVICE_DISCONNECTED if reason != "revoked" else DEVICE_REVOKED,
				"disconnected_at": now,
			},
		)


def _disconnect_all_devices(session_instance_id: str, reason: str) -> None:
	names = frappe.get_all(
		DEVICE_DOCTYPE,
		filters={"session_instance_id": session_instance_id, "status": DEVICE_CONNECTED},
		pluck="name",
	)
	now = now_datetime()
	for name in names:
		frappe.db.set_value(
			DEVICE_DOCTYPE,
			name,
			{"status": DEVICE_REVOKED, "disconnected_at": now},
		)


def _resolve_link_token(link_token: str, *, touch: bool = True) -> tuple[Any, dict]:
	"""Validate link token → (device doc, session dict). Enforces mobile user match."""
	user = require_logged_in()
	link_token = cstr(link_token).strip()
	if not link_token:
		frappe.throw(_("link_token is required"), frappe.AuthenticationError)

	token_hash = _hash(link_token)
	row = frappe.db.get_value(
		DEVICE_DOCTYPE,
		{"link_token_hash": token_hash, "status": DEVICE_CONNECTED},
		[
			"name",
			"device_id",
			"session_instance_id",
			"mobile_user",
			"link_token_expires_at",
			"status",
			"pos_profile",
		],
		as_dict=True,
		for_update=True,
	)
	if not row:
		frappe.throw(_("Invalid or revoked link token"), frappe.AuthenticationError)

	if row.mobile_user != user and "System Manager" not in frappe.get_roles(user):
		frappe.throw(_("Link token belongs to another user"), frappe.PermissionError)

	if get_datetime(row.link_token_expires_at) < now_datetime():
		frappe.db.set_value(DEVICE_DOCTYPE, row.name, "status", DEVICE_REVOKED)
		frappe.throw(_("Link token has expired"), frappe.AuthenticationError)

	session = _get_session(row.session_instance_id)
	if session.status == SESSION_CLOSED:
		frappe.throw(_("POS session is closed"), frappe.ValidationError)

	device = frappe.get_doc(DEVICE_DOCTYPE, row.name)
	if touch:
		device.last_seen = now_datetime()
		device.flags.ignore_permissions = True
		device.save()

	return device, session


# ---------------------------------------------------------------------------
# Cart snapshot (mobile read)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_cart_snapshot(link_token: str):
	"""Mobile reads the POS-published cart snapshot for reconnect/compare."""
	require_mobile_scanner()
	_device, session = _resolve_link_token(link_token)
	snapshot = _parse_json(session.cart_snapshot, "cart_snapshot") or {"items": []}
	return {
		"session": _public_session(session),
		"cart_generation": session.cart_generation,
		"payment_busy": cint(session.payment_busy),
		"snapshot": snapshot,
		"reachable": _session_is_reachable(session),
	}


@frappe.whitelist()
def get_session_status(link_token: str):
	"""Lightweight reachability / generation check for the mobile client."""
	require_mobile_scanner()
	device, session = _resolve_link_token(link_token)
	return {
		"device_id": device.device_id,
		"session": _public_session(session),
	}


# ---------------------------------------------------------------------------
# Command journal
# ---------------------------------------------------------------------------


@frappe.whitelist()
def enqueue_command(
	link_token: str,
	operation_id: str,
	cart_generation: str,
	command_type: str = CMD_ADD_ITEM,
	item_code: str | None = None,
	qty: float | str | None = None,
	uom: str | None = None,
	batch_id: str | None = None,
	created_at: str | None = None,
	payload: str | dict | None = None,
):
	"""Enqueue one command. Idempotent on operation_id."""
	require_mobile_scanner()
	device, session = _resolve_link_token(link_token)

	operation_id = cstr(operation_id).strip()
	if not operation_id:
		frappe.throw(_("operation_id is required"), frappe.ValidationError)

	command_type = cstr(command_type).strip() or CMD_ADD_ITEM
	if command_type not in COMMAND_TYPES:
		frappe.throw(_("Unsupported command_type"), frappe.ValidationError)

	cart_generation = cstr(cart_generation).strip()
	if not cart_generation:
		frappe.throw(_("cart_generation is required"), frappe.ValidationError)

	# Reject commands aimed at a stale/closed sale generation when session has one
	if session.cart_generation and session.cart_generation != cart_generation:
		frappe.throw(
			_("cart_generation mismatch — POS sale changed; reconnect and choose a recovery action"),
			frappe.ValidationError,
			title="CART_GENERATION_MISMATCH",
		)

	if not _session_is_reachable(session):
		# Still accept into journal so mobile can park work, but mark session disconnected
		# for POS-side visibility. TZ: not applied until POS ACK.
		if session.status == SESSION_ACTIVE:
			frappe.db.set_value(SESSION_DOCTYPE, session.name, "status", SESSION_DISCONNECTED)

	extra = _parse_json(payload, "payload") or {}
	if not isinstance(extra, dict):
		frappe.throw(_("payload must be a JSON object"), frappe.ValidationError)

	body = {
		"command_type": command_type,
		"session_instance_id": session.session_instance_id,
		"device_id": device.device_id,
		"cart_generation": cart_generation,
		"item_code": cstr(item_code).strip() or extra.get("item_code"),
		"qty": qty if qty is not None else extra.get("qty"),
		"uom": cstr(uom).strip() or extra.get("uom"),
		"batch_id": cstr(batch_id).strip() or extra.get("batch_id"),
		"items": extra.get("items"),
	}
	# Merge any extra keys for storage (rates etc. ignored by POS applicator)
	stored_payload = {**extra, **{k: v for k, v in body.items() if v is not None}}

	if command_type == CMD_ADD_ITEM:
		if not stored_payload.get("item_code"):
			frappe.throw(_("item_code is required for add_item"), frappe.ValidationError)
		try:
			q = float(stored_payload.get("qty") if stored_payload.get("qty") is not None else 1)
		except (TypeError, ValueError):
			frappe.throw(_("qty must be a number"), frappe.ValidationError)
		if q <= 0:
			frappe.throw(_("qty must be positive"), frappe.ValidationError)
		stored_payload["qty"] = q

	return _upsert_command(
		operation_id=operation_id,
		session=session,
		device=device,
		command_type=command_type,
		cart_generation=cart_generation,
		batch_id=cstr(batch_id).strip() or None,
		created_at=created_at,
		stored_payload=stored_payload,
	)


@frappe.whitelist()
def enqueue_commands(link_token: str, commands: str | list):
	"""Enqueue a batch of commands. Each keeps its own operation_id; optional shared batch_id."""
	require_mobile_scanner()
	device, session = _resolve_link_token(link_token)
	items = _parse_json(commands, "commands")
	if not isinstance(items, list) or not items:
		frappe.throw(_("commands must be a non-empty list"), frappe.ValidationError)

	results = []
	for raw in items:
		if not isinstance(raw, dict):
			frappe.throw(_("Each command must be an object"), frappe.ValidationError)
		results.append(
			enqueue_command(
				link_token=link_token,
				operation_id=raw.get("operation_id"),
				cart_generation=raw.get("cart_generation") or session.cart_generation,
				command_type=raw.get("command_type") or CMD_ADD_ITEM,
				item_code=raw.get("item_code"),
				qty=raw.get("qty"),
				uom=raw.get("uom"),
				batch_id=raw.get("batch_id"),
				created_at=raw.get("created_at"),
				payload=raw,
			)
		)
	return {"results": results}


def _upsert_command(
	*,
	operation_id: str,
	session: dict,
	device: Any,
	command_type: str,
	cart_generation: str,
	batch_id: str | None,
	created_at: str | None,
	stored_payload: dict,
) -> dict:
	"""Insert or return prior result; reject same-id different payload."""
	p_hash = payload_hash(stored_payload)

	existing = frappe.db.get_value(
		COMMAND_DOCTYPE,
		{"operation_id": operation_id},
		[
			"name",
			"operation_id",
			"batch_id",
			"command_type",
			"status",
			"session_instance_id",
			"device_id",
			"cart_generation",
			"payload_json",
			"payload_hash",
			"result_json",
			"created_at_client",
			"delivered_at",
			"acked_at",
			"creation",
		],
		as_dict=True,
		for_update=True,
	)

	if existing:
		if not payloads_match(existing.payload_hash, stored_payload):
			frappe.throw(
				_("operation_id already exists with a different payload"),
				frappe.ValidationError,
				title="OPERATION_ID_CONFLICT",
			)
		# Same payload → return prior result (idempotent)
		return {
			"duplicate": True,
			"command": _command_public(existing),
		}

	try:
		doc = frappe.get_doc(
			{
				"doctype": COMMAND_DOCTYPE,
				"operation_id": operation_id,
				"batch_id": batch_id,
				"command_type": command_type,
				"status": STATUS_QUEUED,
				"session_instance_id": session.session_instance_id,
				"device_id": device.device_id,
				"mobile_user": device.mobile_user,
				"cart_generation": cart_generation,
				"payload_json": _dump_json(stored_payload),
				"payload_hash": p_hash,
				"created_at_client": get_datetime(created_at) if created_at else now_datetime(),
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
	except frappe.DuplicateEntryError:
		# Race: another request inserted the same operation_id
		return _upsert_command(
			operation_id=operation_id,
			session=session,
			device=device,
			command_type=command_type,
			cart_generation=cart_generation,
			batch_id=batch_id,
			created_at=created_at,
			stored_payload=stored_payload,
		)

	audit.record(
		event_type="command_enqueued",
		session_instance_id=session.session_instance_id,
		pos_profile=session.pos_profile,
		user=device.mobile_user,
		device_id=device.device_id,
		details={"operation_id": operation_id, "command_type": command_type},
	)

	publish_command(
		session.session_instance_id,
		{
			"type": "command_queued",
			"operation_id": operation_id,
			"command_type": command_type,
			"batch_id": batch_id,
		},
	)

	return {"duplicate": False, "command": _command_public(doc.as_dict())}


@frappe.whitelist()
def get_command_status(link_token: str, operation_id: str | None = None, batch_id: str | None = None):
	"""Mobile polls command status by operation_id and/or batch_id."""
	require_mobile_scanner()
	device, session = _resolve_link_token(link_token)
	operation_id = cstr(operation_id).strip() if operation_id else ""
	batch_id = cstr(batch_id).strip() if batch_id else ""
	if not operation_id and not batch_id:
		frappe.throw(_("operation_id or batch_id is required"), frappe.ValidationError)

	filters: dict[str, Any] = {"session_instance_id": session.session_instance_id}
	if operation_id:
		filters["operation_id"] = operation_id
	if batch_id:
		filters["batch_id"] = batch_id
	# Scope to this device unless System Manager
	if "System Manager" not in frappe.get_roles():
		filters["device_id"] = device.device_id

	rows = frappe.get_all(
		COMMAND_DOCTYPE,
		filters=filters,
		fields=[
			"operation_id",
			"batch_id",
			"command_type",
			"status",
			"session_instance_id",
			"device_id",
			"cart_generation",
			"payload_json",
			"result_json",
			"created_at_client",
			"delivered_at",
			"acked_at",
			"creation",
		],
		order_by="creation asc",
	)
	return {"commands": [_command_public(r) for r in rows]}


@frappe.whitelist()
def poll_commands(session_instance_id: str, statuses: str | None = None, limit: int | str = 50):
	"""POS till polls pending commands (realtime fallback).

	Default statuses: queued, delivered (unacked). Marks queued → delivered on fetch.
	"""
	user = require_cashier_or_manager()
	session = _get_session(session_instance_id)
	assert_session_cashier(session, user)

	wanted = None
	if statuses:
		parsed = _parse_json(statuses, "statuses") if isinstance(statuses, str) and statuses.startswith("[") else None
		if parsed is None:
			wanted = [s.strip() for s in cstr(statuses).split(",") if s.strip()]
		else:
			wanted = [cstr(s).strip() for s in parsed]
	else:
		wanted = [STATUS_QUEUED, STATUS_DELIVERED]

	limit = max(1, min(cint(limit) or 50, 200))
	rows = frappe.get_all(
		COMMAND_DOCTYPE,
		filters={
			"session_instance_id": session.session_instance_id,
			"status": ("in", wanted),
		},
		fields=[
			"name",
			"operation_id",
			"batch_id",
			"command_type",
			"status",
			"session_instance_id",
			"device_id",
			"cart_generation",
			"payload_json",
			"result_json",
			"created_at_client",
			"delivered_at",
			"acked_at",
			"creation",
		],
		order_by="creation asc",
		limit_page_length=limit,
	)

	now = now_datetime()
	out = []
	for row in rows:
		if row.status == STATUS_QUEUED:
			frappe.db.set_value(
				COMMAND_DOCTYPE,
				row.name,
				{"status": STATUS_DELIVERED, "delivered_at": now},
			)
			row.status = STATUS_DELIVERED
			row.delivered_at = now
		out.append(_command_public(row))

	return {"commands": out, "session_instance_id": session.session_instance_id}


@frappe.whitelist()
def ack_command(
	session_instance_id: str,
	operation_id: str,
	status: str,
	result: str | dict | None = None,
):
	"""POS till acknowledges apply/reject/unknown after cart mutation.

	Stub-ready: POS frontend must call this after ``cartStore.addItem`` (or reject).
	Server accept alone never marks applied.
	"""
	user = require_cashier_or_manager()
	session = _get_session(session_instance_id)
	assert_session_cashier(session, user)

	operation_id = cstr(operation_id).strip()
	status = cstr(status).strip()
	if status not in ACK_STATUSES:
		frappe.throw(
			_("ACK status must be one of: {0}").format(", ".join(ACK_STATUSES)),
			frappe.ValidationError,
		)

	row = frappe.db.get_value(
		COMMAND_DOCTYPE,
		{"operation_id": operation_id, "session_instance_id": session.session_instance_id},
		["name", "status", "operation_id", "payload_hash"],
		as_dict=True,
		for_update=True,
	)
	if not row:
		frappe.throw(_("Command not found"), frappe.DoesNotExistError)

	# Idempotent ACK: same terminal status + ignore duplicate ACK
	if row.status in ACK_STATUSES:
		existing = frappe.get_doc(COMMAND_DOCTYPE, row.name)
		return {"duplicate": True, "command": _command_public(existing.as_dict())}

	doc = frappe.get_doc(COMMAND_DOCTYPE, row.name)
	doc.status = status
	doc.acked_at = now_datetime()
	doc.acked_by = user
	if result is not None:
		doc.result_json = _dump_json(_parse_json(result, "result") if not isinstance(result, dict) else result)
	doc.flags.ignore_permissions = True
	doc.save()

	audit.record(
		event_type="command_acked",
		session_instance_id=session.session_instance_id,
		pos_profile=session.pos_profile,
		user=user,
		device_id=doc.device_id,
		details={"operation_id": operation_id, "status": status},
	)

	publish_command(
		session.session_instance_id,
		{"type": "command_acked", "operation_id": operation_id, "status": status},
	)

	return {"duplicate": False, "command": _command_public(doc.as_dict())}
