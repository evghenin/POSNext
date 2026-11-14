# Copyright (c) 2024, POS Next and contributors
# For license information, please see license.txt

import frappe
from frappe import translate


@frappe.whitelist()
def get_app_translations(locale=None):
	"""
	Get POS interface translations for an explicit locale.

	The locale is the cashier's POS language, not User.language (Desk).
	When omitted, the saved POS language is used, then English.

	Returns:
		dict: Translation dictionary {source: translated}
	"""
	lang = (locale or _get_pos_language() or "en").lower()
	allowed = get_allowed_locales_from_settings()
	if lang not in allowed:
		lang = "en" if "en" in allowed else next(iter(allowed))
	return translate.get_all_translations(lang)


@frappe.whitelist()
def get_user_language():
	"""
	Get the language preference for the current user.

	Returns:
		dict: User's language preference

	Security checks:
	- User must be authenticated (not Guest)
	"""
	# Check if user is authenticated
	if frappe.session.user == "Guest":
		frappe.throw("Authentication required", frappe.AuthenticationError)

	return {"success": True, "locale": _get_pos_language() or "en"}


@frappe.whitelist()
def get_allowed_locales():
	"""
	Get list of allowed locales from POS Settings for the language switcher.

	Returns:
		dict: List of allowed locale codes
	"""
	allowed = get_allowed_locales_from_settings()
	return {"success": True, "locales": list(allowed)}


def _get_pos_language():
	"""Cashier's POS interface language. Empty when they have not chosen one."""
	if not frappe.db.has_column("User", "pos_language"):
		return None
	lang = frappe.db.get_value("User", frappe.session.user, "pos_language")
	return (lang or "").lower() or None


def get_allowed_locales_from_settings():
	"""
	Get allowed locales from POS Settings.
	Falls back to default locales if not configured.

	Returns:
		set: Set of allowed locale codes
	"""
	default_locales = {"ar", "en"}

	try:
		# Get the first POS Settings (or we could use a specific one based on user's profile)
		pos_settings_list = frappe.get_all("POS Settings", filters={"enabled": 1}, fields=["name"], limit=1)

		if not pos_settings_list:
			return default_locales

		pos_settings = frappe.get_doc("POS Settings", pos_settings_list[0].name)

		if pos_settings.allowed_locales and len(pos_settings.allowed_locales) > 0:
			return {row.language.lower() for row in pos_settings.allowed_locales}

		return default_locales
	except Exception:
		return default_locales


@frappe.whitelist()
def change_user_language(locale):
	"""
	Change the POS interface language for the current cashier.

	Writes User.pos_language. User.language (Desk) is left unchanged.

	Args:
		locale (str): Language code (e.g., 'en', 'ar')

	Returns:
		dict: Success status and message

	Security checks:
	- User must be authenticated (not Guest)
	- User must be enabled
	"""
	# Check if user is authenticated
	if frappe.session.user == "Guest":
		frappe.throw("Authentication required", frappe.AuthenticationError)

	# Verify user is enabled
	if not frappe.db.get_value("User", frappe.session.user, "enabled"):
		frappe.throw("User is disabled", frappe.AuthenticationError)

	# Validate locale parameter
	if not locale:
		frappe.throw("Locale parameter is required", frappe.ValidationError)

	# Normalize locale to lowercase
	locale = locale.lower()

	allowed_locales = get_allowed_locales_from_settings()
	if locale not in allowed_locales:
		frappe.throw(f"Locale '{locale}' is not supported", frappe.ValidationError)

	# POS interface language only. Desk keeps User.language.
	try:
		frappe.db.set_value("User", frappe.session.user, "pos_language", locale)
		frappe.db.commit()

		return {"success": True, "message": f"Language changed to {locale}", "locale": locale}
	except Exception as e:
		frappe.log_error(f"Failed to change user language: {e!s}")
		frappe.throw(f"Failed to change language: {e!s}", frappe.ValidationError)
