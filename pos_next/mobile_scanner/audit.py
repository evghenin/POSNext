# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Append-only audit trail for mobile scanner events."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import now_datetime

from pos_next.mobile_scanner.constants import AUDIT_DOCTYPE


def record(
	*,
	event_type: str,
	session_instance_id: str | None = None,
	pos_profile: str | None = None,
	device_id: str | None = None,
	user: str | None = None,
	details: dict[str, Any] | str | None = None,
) -> None:
	"""Write one audit row. Never raises — auditing must not break the till."""
	try:
		if isinstance(details, dict):
			details_text = json.dumps(details, default=str, sort_keys=True)[:1000]
		else:
			details_text = (details or "")[:1000]

		doc = frappe.get_doc(
			{
				"doctype": AUDIT_DOCTYPE,
				"timestamp": now_datetime(),
				"event_type": event_type,
				"user": user or frappe.session.user,
				"device_id": device_id,
				"session_instance_id": session_instance_id,
				"pos_profile": pos_profile,
				"details": details_text,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "POS Mobile Audit Log Error")
