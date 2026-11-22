# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Pure unit tests for mobile scanner crypto + payload hashing (no Frappe required).

Run without a bench site:
    python -m unittest pos_next.mobile_scanner.tests.test_crypto_payload -v
"""

from __future__ import annotations

import unittest

from pos_next.mobile_scanner.crypto import (
	generate_pin,
	generate_token,
	hash_secret,
	pin_alphabet_ok,
	secrets_equal,
)
from pos_next.mobile_scanner.payload import canonicalize_payload, payload_hash, payloads_match


class TestCrypto(unittest.TestCase):
	def test_generate_pin_length_and_digits(self):
		pin = generate_pin(6)
		self.assertEqual(len(pin), 6)
		self.assertTrue(pin.isdigit())

	def test_pin_alphabet_ok(self):
		self.assertTrue(pin_alphabet_ok("012345", 6))
		self.assertFalse(pin_alphabet_ok("12345", 6))
		self.assertFalse(pin_alphabet_ok("12345a", 6))

	def test_hash_secret_is_stable_and_peppered(self):
		a = hash_secret("123456", pepper="site-a")
		b = hash_secret("123456", pepper="site-a")
		c = hash_secret("123456", pepper="site-b")
		self.assertEqual(a, b)
		self.assertNotEqual(a, c)
		self.assertNotEqual(a, "123456")

	def test_secrets_equal_constant_time_compare(self):
		h = hash_secret("abc", pepper="p")
		self.assertTrue(secrets_equal(h, hash_secret("abc", pepper="p")))
		self.assertFalse(secrets_equal(h, hash_secret("abd", pepper="p")))
		self.assertFalse(secrets_equal(h, None))

	def test_generate_token_urlsafe(self):
		t = generate_token(16)
		self.assertGreater(len(t), 10)
		self.assertNotEqual(t, generate_token(16))


class TestPayloadHash(unittest.TestCase):
	def test_same_payload_same_hash(self):
		p1 = {"command_type": "add_item", "item_code": "sku00673", "qty": 3, "uom": "Nos"}
		p2 = {"command_type": "add_item", "item_code": "SKU00673", "qty": 3.0, "uom": "Nos"}
		self.assertEqual(payload_hash(p1), payload_hash(p2))
		self.assertTrue(payloads_match(payload_hash(p1), p2))

	def test_different_payload_different_hash(self):
		p1 = {"command_type": "add_item", "item_code": "SKU1", "qty": 1, "uom": "Nos"}
		p2 = {"command_type": "add_item", "item_code": "SKU1", "qty": 2, "uom": "Nos"}
		self.assertNotEqual(payload_hash(p1), payload_hash(p2))
		self.assertFalse(payloads_match(payload_hash(p1), p2))

	def test_canonicalize_ignores_untrusted_price(self):
		"""Mobile-sent rate must not affect idempotency key."""
		base = {"command_type": "add_item", "item_code": "A", "qty": 1, "uom": "Nos"}
		with_rate = {**base, "rate": 99.0}
		self.assertEqual(canonicalize_payload(base), canonicalize_payload(with_rate))
		self.assertEqual(payload_hash(base), payload_hash(with_rate))

	def test_batch_id_and_items_included(self):
		a = {"command_type": "merge_cart", "batch_id": "b1", "items": [{"item_code": "X", "qty": 1}]}
		b = {"command_type": "merge_cart", "batch_id": "b1", "items": [{"item_code": "X", "qty": 2}]}
		self.assertNotEqual(payload_hash(a), payload_hash(b))


if __name__ == "__main__":
	unittest.main()
