# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Scanner item lookup shape. No Frappe required."""

from __future__ import annotations

import unittest

from pos_next.mobile_scanner.item_lookup import (
	found_payload,
	not_found_payload,
	price_per_base_unit,
	uoms_with_base_conversion,
)


class TestPricePerBaseUnit(unittest.TestCase):
	def test_uses_stock_uom_rate(self):
		self.assertEqual(price_per_base_unit({"Nos": 10, "Box": 100}, "Nos"), 10.0)

	def test_blank_uom_is_the_base_price(self):
		self.assertEqual(price_per_base_unit({"": 4.5, "Box": 40}, "Nos"), 4.5)

	def test_other_uom_alone_is_not_the_base_price(self):
		self.assertIsNone(price_per_base_unit({"Box": 40}, "Nos"))

	def test_missing_prices(self):
		self.assertIsNone(price_per_base_unit(None, "Nos"))


class TestUomConversion(unittest.TestCase):
	def test_base_unit_is_first_and_other_uoms_keep_their_factor(self):
		rows = uoms_with_base_conversion(
			"Nos",
			[{"uom": "Box", "conversion_factor": 12}, {"uom": "Nos", "conversion_factor": 1}],
		)
		self.assertEqual(
			rows,
			[
				{"uom": "Nos", "conversion_factor": 1.0},
				{"uom": "Box", "conversion_factor": 12.0},
			],
		)


class TestPayload(unittest.TestCase):
	def test_found_shape(self):
		payload = found_payload(
			code="sku00012",
			item_code="SKU00012",
			item_name="Prija",
			image="/files/prija.jpg",
			stock_uom="Nos",
			uom_prices={"Nos": 25},
			conversions=[{"uom": "Box", "conversion_factor": 12}],
			currency="MDL",
			matched_by="item_code",
			barcode_uom=None,
		)
		self.assertTrue(payload["found"])
		self.assertEqual(payload["item_code"], "SKU00012")
		self.assertEqual(payload["item_name"], "Prija")
		self.assertEqual(payload["image"], "/files/prija.jpg")
		self.assertEqual(payload["price"], 25.0)
		self.assertEqual(payload["stock_uom"], "Nos")
		self.assertEqual(payload["uoms"][1]["conversion_factor"], 12.0)

	def test_not_found_shape(self):
		self.assertEqual(
			not_found_payload("NOPE"),
			{"found": False, "code": "NOPE", "reason": "not_found"},
		)
