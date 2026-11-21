# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class POSMobileCommand(Document):
	"""Idempotent command journal entry keyed by operation_id (UUID)."""

	pass
