# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Tunables for mobile scanner pairing and command journal."""

# Pairing challenge
PAIRING_TTL_SECONDS = 120
PAIRING_PIN_LENGTH = 6
PAIRING_MAX_ATTEMPTS = 5

# Link token issued after successful pairing (PIN is never reused as the secret)
LINK_TOKEN_TTL_SECONDS = 12 * 60 * 60

# POS tab considered unavailable when heartbeat is older than this
HEARTBEAT_STALE_SECONDS = 45

# DocType names
SESSION_DOCTYPE = "POS Mobile Session"
CHALLENGE_DOCTYPE = "POS Mobile Pairing Challenge"
DEVICE_DOCTYPE = "POS Mobile Device"
COMMAND_DOCTYPE = "POS Mobile Command"
AUDIT_DOCTYPE = "POS Mobile Audit Log"

# Roles
ROLE_MOBILE_SCANNER = "POSNext Mobile Scanner"
ROLE_CASHIER = "POSNext Cashier"
ROLE_MANAGER = "Nexus POS Manager"

# Command statuses (server journal)
STATUS_QUEUED = "queued"
STATUS_DELIVERED = "delivered"
STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"
STATUS_UNKNOWN = "unknown"

COMMAND_STATUSES = (
	STATUS_QUEUED,
	STATUS_DELIVERED,
	STATUS_APPLIED,
	STATUS_REJECTED,
	STATUS_UNKNOWN,
)

# Terminal ACK statuses the POS client may report
ACK_STATUSES = (
	STATUS_APPLIED,
	STATUS_REJECTED,
	STATUS_UNKNOWN,
)

# Command types
CMD_ADD_ITEM = "add_item"
CMD_REPLACE_CART = "replace_cart"
CMD_MERGE_CART = "merge_cart"

COMMAND_TYPES = (CMD_ADD_ITEM, CMD_REPLACE_CART, CMD_MERGE_CART)

# Realtime event
REALTIME_EVENT = "pos_mobile_command"

# Session / device / challenge statuses
SESSION_ACTIVE = "Active"
SESSION_DISCONNECTED = "Disconnected"
SESSION_CLOSED = "Closed"

DEVICE_CONNECTED = "Connected"
DEVICE_DISCONNECTED = "Disconnected"
DEVICE_REVOKED = "Revoked"

CHALLENGE_OPEN = "Open"
CHALLENGE_REDEEMED = "Redeemed"
CHALLENGE_EXPIRED = "Expired"
CHALLENGE_REVOKED = "Revoked"
