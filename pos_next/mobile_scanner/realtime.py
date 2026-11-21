# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Realtime signalling for mobile scanner commands (signal only — journal is source of truth)."""

from __future__ import annotations

from typing import Any

import frappe

from pos_next.mobile_scanner.constants import REALTIME_EVENT


def publish_command(session_instance_id: str, message: dict[str, Any]) -> None:
	"""Notify the POS tab that a new command is available.

	Uses ``room=session_instance_id`` so only the paired till receives it.
	Realtime is best-effort; clients must poll as fallback.
	"""
	if not session_instance_id:
		return
	try:
		payload = dict(message or {})
		payload.setdefault("session_instance_id", session_instance_id)
		frappe.publish_realtime(
			event=REALTIME_EVENT,
			message=payload,
			room=session_instance_id,
			after_commit=True,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "POS Mobile Realtime Publish Error")
