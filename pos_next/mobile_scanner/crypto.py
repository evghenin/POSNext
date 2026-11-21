# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""PIN / token generation and hashing (stdlib only — no Frappe import)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string


def generate_pin(length: int = 6) -> str:
	"""Return a numeric PIN of ``length`` digits (leading zeros allowed)."""
	if length < 4 or length > 12:
		raise ValueError("PIN length must be between 4 and 12")
	# secrets.randbelow avoids modulo bias
	upper = 10**length
	return f"{secrets.randbelow(upper):0{length}d}"


def generate_token(nbytes: int = 32) -> str:
	"""Return a URL-safe opaque token."""
	return secrets.token_urlsafe(nbytes)


def generate_uuid() -> str:
	"""Return a random UUID4 string."""
	return str(__import__("uuid").uuid4())


def hash_secret(value: str, *, pepper: str = "") -> str:
	"""Deterministic SHA-256 hex digest of ``value`` with optional pepper.

	Used for pairing PIN, QR token, and link token at rest. Comparison must use
	:func:`secrets_equal` (constant-time).
	"""
	material = f"{pepper}:{value or ''}"
	return hashlib.sha256(material.encode("utf-8")).hexdigest()


def secrets_equal(left: str, right: str) -> bool:
	"""Constant-time equality for hex digests / tokens."""
	if left is None or right is None:
		return False
	return hmac.compare_digest(str(left), str(right))


def pin_alphabet_ok(pin: str, length: int = 6) -> bool:
	"""True when ``pin`` is exactly ``length`` decimal digits."""
	pin = (pin or "").strip()
	return len(pin) == length and all(ch in string.digits for ch in pin)
