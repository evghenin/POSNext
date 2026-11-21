# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class POSMobilePairingChallenge(Document):
	"""Short-lived one-time PIN/QR challenge bound to a POS session instance."""

	pass
