# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Phone auth policy: bearer link token, no ERPNext user session required.

The scanner app does not send a user, password, or API key. Redeeming a
one-time PIN/QR and later cart calls authenticate as Guest plus that secret.
"""

from __future__ import annotations

GUEST_USER = "Guest"

# Phone methods that must be callable without an ERPNext login.
PHONE_METHODS = (
	"redeem_pairing",
	"disconnect_self",
	"get_cart_snapshot",
	"get_session_status",
	"lookup_item",
	"enqueue_command",
	"enqueue_commands",
	"get_command_status",
)

# Till methods stay on the cashier session. They are not phone entry points.
TILL_METHODS = (
	"register_session",
	"heartbeat",
	"update_cart_snapshot",
	"close_session",
	"create_pairing_challenge",
	"revoke_pairing_challenge",
	"list_devices",
	"disconnect_device",
	"poll_commands",
	"ack_command",
)


def phone_actor(session_user: str | None) -> str:
	"""User to record for a phone call. Guest when the phone is not logged in."""
	user = (session_user or "").strip()
	if not user or user == GUEST_USER:
		return GUEST_USER
	return user


def link_token_user_allowed(
	*,
	session_user: str | None,
	mobile_user: str | None,
	is_system_manager: bool = False,
) -> bool:
	"""Bearer link token is enough for Guest.

	A logged-in caller must own the token (or be System Manager) so a desk
	session cannot present another user's token. Guest is the phone path:
	the token itself is the credential, including tokens issued earlier to a
	named user.
	"""
	if is_system_manager:
		return True
	if phone_actor(session_user) == GUEST_USER:
		return True
	return (mobile_user or "") == phone_actor(session_user)
