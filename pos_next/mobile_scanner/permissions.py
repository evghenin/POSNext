# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Server-side permission checks for mobile scanner APIs."""

from __future__ import annotations

import frappe
from frappe import _

from pos_next.mobile_scanner.constants import ROLE_CASHIER, ROLE_MANAGER, ROLE_MOBILE_SCANNER


def _is_system_manager(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return "System Manager" in frappe.get_roles(user)


def user_has_any_role(roles: tuple[str, ...] | list[str], user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _is_system_manager(user):
		return True
	have = set(frappe.get_roles(user))
	return bool(have.intersection(roles))


def require_logged_in() -> str:
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Authentication required"), frappe.AuthenticationError)
	return user


def require_cashier_or_manager(user: str | None = None) -> str:
	"""POS till APIs: cashier/manager (or System Manager)."""
	user = user or require_logged_in()
	if not user_has_any_role((ROLE_CASHIER, ROLE_MANAGER), user):
		frappe.throw(_("Not permitted to manage mobile scanner sessions"), frappe.PermissionError)
	return user


def require_mobile_scanner(user: str | None = None) -> str:
	"""Role check for a logged-in scanner user.

	Phone APIs do not call this. They allow Guest and authenticate with the
	one-time PIN/QR or the issued link_token.
	"""
	user = user or require_logged_in()
	if not user_has_any_role((ROLE_MOBILE_SCANNER, ROLE_CASHIER, ROLE_MANAGER), user):
		frappe.throw(_("Not permitted to use the mobile scanner"), frappe.PermissionError)
	return user


def assert_pos_profile_access(pos_profile: str, user: str | None = None) -> None:
	"""Caller must be on the POS Profile User table (or System Manager / profile write)."""
	user = user or frappe.session.user
	if not pos_profile:
		frappe.throw(_("POS Profile is required"), frappe.ValidationError)

	if _is_system_manager(user):
		return

	if frappe.has_permission("POS Profile", "write", user=user):
		return

	assigned = frappe.db.exists("POS Profile User", {"parent": pos_profile, "user": user})
	if not assigned:
		frappe.throw(
			_("You are not assigned to POS Profile {0}").format(pos_profile),
			frappe.PermissionError,
		)


def assert_session_cashier(session: dict, user: str | None = None) -> None:
	"""Only the cashier who owns the session (or System Manager) may manage it from POS."""
	user = user or frappe.session.user
	if _is_system_manager(user):
		return
	if session.get("cashier_user") != user:
		frappe.throw(_("You do not own this POS mobile session"), frappe.PermissionError)


def get_profile_context(pos_profile: str) -> dict:
	"""Resolve company/warehouse from POS Profile — callers cannot invent them."""
	row = frappe.db.get_value(
		"POS Profile",
		pos_profile,
		["name", "company", "warehouse"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("POS Profile {0} not found").format(pos_profile), frappe.ValidationError)
	return row


def assert_opening_shift(pos_opening_shift: str | None, pos_profile: str, user: str) -> dict | None:
	"""Validate opening shift belongs to this profile/user when provided."""
	if not pos_opening_shift:
		return None

	shift = frappe.db.get_value(
		"POS Opening Shift",
		pos_opening_shift,
		["name", "pos_profile", "user", "status", "company", "docstatus"],
		as_dict=True,
	)
	if not shift:
		frappe.throw(_("POS Opening Shift {0} not found").format(pos_opening_shift), frappe.ValidationError)

	if shift.pos_profile != pos_profile:
		frappe.throw(_("Opening shift does not belong to this POS Profile"), frappe.ValidationError)

	if shift.user and shift.user != user and not _is_system_manager(user):
		frappe.throw(_("Opening shift belongs to another user"), frappe.PermissionError)

	if shift.status and shift.status not in ("Open", "Draft"):
		frappe.throw(_("Opening shift is not open"), frappe.ValidationError)

	return shift
