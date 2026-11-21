# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Unit / mock tests for pos_next.api.mobile_scanner.

Pure crypto/payload tests live in
``pos_next.mobile_scanner.tests.test_crypto_payload`` and run without Frappe.

These tests exercise API helpers with mocks. Full end-to-end DocType tests need a
bench site:

    bench --site <site> run-tests --app pos_next --module pos_next.api.test_mobile_scanner

Or from the app root (with Frappe on PYTHONPATH):

    python -m unittest pos_next.api.test_mobile_scanner -v
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
	import frappe
	from pos_next.api import mobile_scanner as api
except ModuleNotFoundError:  # pragma: no cover - local runs without Frappe
	frappe = None
	api = None

from pos_next.mobile_scanner.constants import STATUS_APPLIED, STATUS_QUEUED
from pos_next.mobile_scanner.crypto import hash_secret
from pos_next.mobile_scanner.payload import payload_hash


def _skip_without_frappe(cls):
	return unittest.skipIf(frappe is None or api is None, "Frappe not installed")(cls)


def _raise_validation(message, *args, **kwargs):
	exc = kwargs.get("exc") or frappe.ValidationError
	raise exc(str(message))


@_skip_without_frappe
class TestPayloadIdempotencyHelpers(unittest.TestCase):
	def test_payloads_match_helper_used_by_upsert(self):
		payload = {
			"command_type": "add_item",
			"session_instance_id": "s1",
			"device_id": "d1",
			"cart_generation": "g1",
			"item_code": "SKU1",
			"qty": 1,
			"uom": "Nos",
		}
		h = payload_hash(payload)
		self.assertTrue(api.payloads_match(h, payload))
		self.assertFalse(api.payloads_match(h, {**payload, "qty": 2}))


@_skip_without_frappe
class TestUpsertCommandIdempotency(unittest.TestCase):
	"""Mirrors Offline Invoice Sync uniqueness: same id → prior result; conflict → reject."""

	def setUp(self):
		self.session = SimpleNamespace(
			session_instance_id="sess-1",
			pos_profile="Profile A",
			name="SESS-DOC",
			cart_generation="gen-1",
			status="Active",
		)
		self.device = SimpleNamespace(device_id="dev-1", mobile_user="scanner@example.com")
		self.payload = {
			"command_type": "add_item",
			"session_instance_id": "sess-1",
			"device_id": "dev-1",
			"cart_generation": "gen-1",
			"item_code": "SKU1",
			"qty": 1,
			"uom": "Nos",
		}

	@patch("pos_next.api.mobile_scanner.publish_command")
	@patch("pos_next.api.mobile_scanner.audit.record")
	@patch("pos_next.api.mobile_scanner.frappe")
	def test_duplicate_same_payload_returns_prior(self, mock_frappe, _audit, _pub):
		existing = SimpleNamespace(
			name="CMD-1",
			operation_id="op-1",
			batch_id=None,
			command_type="add_item",
			status=STATUS_APPLIED,
			session_instance_id="sess-1",
			device_id="dev-1",
			cart_generation="gen-1",
			payload_json="{}",
			payload_hash=payload_hash(self.payload),
			result_json='{"ok": true}',
			created_at_client=None,
			delivered_at=None,
			acked_at=None,
			creation=None,
		)
		mock_frappe.db.get_value.return_value = existing
		mock_frappe.ValidationError = frappe.ValidationError

		result = api._upsert_command(
			operation_id="op-1",
			session=self.session,
			device=self.device,
			command_type="add_item",
			cart_generation="gen-1",
			batch_id=None,
			created_at=None,
			stored_payload=self.payload,
		)
		self.assertTrue(result["duplicate"])
		self.assertEqual(result["command"]["operation_id"], "op-1")
		self.assertEqual(result["command"]["status"], STATUS_APPLIED)

	@patch("pos_next.api.mobile_scanner.frappe")
	def test_same_id_different_payload_rejected(self, mock_frappe):
		mock_frappe.db.get_value.return_value = SimpleNamespace(
			name="CMD-1",
			operation_id="op-1",
			payload_hash=payload_hash(self.payload),
			status=STATUS_QUEUED,
		)
		mock_frappe.ValidationError = frappe.ValidationError
		mock_frappe.throw.side_effect = _raise_validation
		with self.assertRaises(frappe.ValidationError):
			api._upsert_command(
				operation_id="op-1",
				session=self.session,
				device=self.device,
				command_type="add_item",
				cart_generation="gen-1",
				batch_id=None,
				created_at=None,
				stored_payload={**self.payload, "qty": 9},
			)


@_skip_without_frappe
class TestPinHashingInApi(unittest.TestCase):
	def test_pepper_hash_differs_from_raw_pin(self):
		with patch.object(api, "_pepper", return_value="test-pepper"):
			h = api._hash("123456")
		self.assertEqual(h, hash_secret("123456", pepper="test-pepper"))
		self.assertNotEqual(h, "123456")


@_skip_without_frappe
class TestSessionReachability(unittest.TestCase):
	@patch("pos_next.api.mobile_scanner.now_datetime")
	@patch("pos_next.api.mobile_scanner.get_datetime")
	def test_stale_heartbeat_not_reachable(self, mock_get_dt, mock_now):
		from datetime import datetime, timedelta

		now = datetime(2026, 11, 21, 12, 0, 0)
		mock_now.return_value = now
		mock_get_dt.side_effect = lambda v: v
		session = SimpleNamespace(
			status="Active",
			last_heartbeat=now - timedelta(seconds=120),
		)
		self.assertFalse(api._session_is_reachable(session))

	@patch("pos_next.api.mobile_scanner.now_datetime")
	@patch("pos_next.api.mobile_scanner.get_datetime")
	def test_fresh_heartbeat_reachable(self, mock_get_dt, mock_now):
		from datetime import datetime, timedelta

		now = datetime(2026, 11, 21, 12, 0, 0)
		mock_now.return_value = now
		mock_get_dt.side_effect = lambda v: v
		session = SimpleNamespace(
			status="Active",
			last_heartbeat=now - timedelta(seconds=10),
		)
		self.assertTrue(api._session_is_reachable(session))


@_skip_without_frappe
class TestCreatePairingChallengeAuth(unittest.TestCase):
	@patch("pos_next.api.mobile_scanner.require_cashier_or_manager", return_value="cashier@example.com")
	@patch("pos_next.api.mobile_scanner._get_session")
	@patch("pos_next.api.mobile_scanner.assert_session_cashier")
	@patch("pos_next.api.mobile_scanner._revoke_open_challenges")
	@patch("pos_next.api.mobile_scanner.audit.record")
	@patch("pos_next.api.mobile_scanner.frappe")
	def test_create_challenge_returns_plaintext_once(
		self, mock_frappe, _audit, _revoke, _assert, mock_session, _auth
	):
		mock_session.return_value = SimpleNamespace(
			session_instance_id="sess-1",
			status="Active",
			pos_profile="Profile A",
			pos_opening_shift="SHIFT-1",
		)

		doc = MagicMock()
		doc.name = "CHAL-1"
		mock_frappe.get_doc.return_value = doc

		with patch.object(api, "_hash", side_effect=lambda v: f"hash:{v}"):
			result = api.create_pairing_challenge("sess-1")

		self.assertEqual(result["challenge_id"], "CHAL-1")
		self.assertEqual(len(result["pin"]), 6)
		self.assertTrue(result["pin"].isdigit())
		self.assertTrue(result["qr_token"])
		# Plaintext pin must not be written on the doc fields — only hashes
		insert_payload = mock_frappe.get_doc.call_args[0][0]
		self.assertNotIn("pin", insert_payload)
		self.assertIn("pin_hash", insert_payload)
		self.assertNotEqual(insert_payload["pin_hash"], result["pin"])


@_skip_without_frappe
class TestAckCommandStub(unittest.TestCase):
	@patch("pos_next.api.mobile_scanner.require_cashier_or_manager", return_value="cashier@example.com")
	@patch("pos_next.api.mobile_scanner._get_session")
	@patch("pos_next.api.mobile_scanner.assert_session_cashier")
	@patch("pos_next.api.mobile_scanner.publish_command")
	@patch("pos_next.api.mobile_scanner.audit.record")
	@patch("pos_next.api.mobile_scanner.frappe")
	def test_ack_sets_applied(self, mock_frappe, _audit, _pub, _assert, mock_session, _auth):
		mock_session.return_value = SimpleNamespace(
			session_instance_id="sess-1",
			pos_profile="Profile A",
			name="SESS",
			cashier_user="cashier@example.com",
		)
		mock_frappe.db.get_value.return_value = SimpleNamespace(
			name="CMD-1",
			status=STATUS_QUEUED,
			operation_id="op-1",
			payload_hash="abc",
		)
		doc = MagicMock()
		doc.device_id = "dev-1"
		doc.operation_id = "op-1"
		doc.status = STATUS_APPLIED
		doc.batch_id = None
		doc.command_type = "add_item"
		doc.session_instance_id = "sess-1"
		doc.cart_generation = "gen-1"
		doc.payload_json = "{}"
		doc.result_json = None
		doc.created_at_client = None
		doc.delivered_at = None
		doc.acked_at = None
		doc.as_dict.return_value = {
			"operation_id": "op-1",
			"batch_id": None,
			"command_type": "add_item",
			"status": STATUS_APPLIED,
			"session_instance_id": "sess-1",
			"device_id": "dev-1",
			"cart_generation": "gen-1",
			"payload_json": "{}",
			"result_json": None,
			"created_at_client": None,
			"delivered_at": None,
			"acked_at": None,
			"creation": None,
		}
		mock_frappe.get_doc.return_value = doc

		result = api.ack_command("sess-1", "op-1", STATUS_APPLIED, result={"line": 1})
		self.assertFalse(result["duplicate"])
		self.assertEqual(doc.status, STATUS_APPLIED)
		doc.save.assert_called_once()


if __name__ == "__main__":
	unittest.main()
