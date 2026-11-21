# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class POSMobileSession(Document):
	"""Durable POS tab/session instance for mobile scanner pairing."""

	def before_insert(self):
		if not self.session_instance_id:
			self.session_instance_id = frappe.generate_hash(length=20)
		if not self.last_heartbeat:
			self.last_heartbeat = frappe.utils.now_datetime()
