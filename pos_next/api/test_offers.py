# Copyright (c) 2025, BrainWise and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import MagicMock, patch

from pos_next.api.offers import (
	_pricing_rule_affects_item,
	item_has_active_promotion,
	validate_coupon,
)


class TestValidateCoupon(unittest.TestCase):
	# new_callable=MagicMock: some environments have unittest.mock auto-detect
	# frappe.db as async and substitute an AsyncMock, which returns coroutines
	# instead of the configured values. Force a plain MagicMock explicitly.
	@patch("pos_next.api.offers.frappe.db", new_callable=MagicMock)
	def test_coupons_not_enabled_takes_precedence_over_missing_customer(self, mock_db):
		"""Table-existence must be checked before the customer requirement, so a
		site without POS Coupon set up reports the accurate reason even when no
		customer is selected either."""
		mock_db.table_exists.return_value = False

		result = validate_coupon(coupon_code="SAVE10", company="Test Company", customer=None)

		self.assertFalse(result["valid"])
		self.assertEqual(result["message"], "Coupons are not enabled")
		# Must never reach the coupon lookup (get_value may still be called by
		# unrelated framework internals, e.g. translation lookups for _()).
		for call in mock_db.get_value.call_args_list:
			self.assertNotEqual(call.args[0] if call.args else None, "POS Coupon")

	@patch("pos_next.api.offers.frappe.db", new_callable=MagicMock)
	def test_missing_customer_is_rejected_with_friendly_message(self, mock_db):
		"""No customer selected must return a clean message, not crash on the
		coupon lookup (regression test for PN-77)."""
		mock_db.table_exists.return_value = True

		result = validate_coupon(coupon_code="SAVE10", company="Test Company", customer=None)

		self.assertFalse(result["valid"])
		self.assertEqual(result["message"], "Please choose a customer")
		for call in mock_db.get_value.call_args_list:
			self.assertNotEqual(call.args[0] if call.args else None, "POS Coupon")

	@patch("pos_next.api.offers.frappe.db", new_callable=MagicMock)
	def test_empty_string_customer_is_also_rejected(self, mock_db):
		"""The frontend sends '' rather than omitting the param — must be treated
		the same as no customer at all."""
		mock_db.table_exists.return_value = True

		result = validate_coupon(coupon_code="SAVE10", company="Test Company", customer="")

		self.assertFalse(result["valid"])
		self.assertEqual(result["message"], "Please choose a customer")

	@patch("pos_next.api.offers.frappe.db", new_callable=MagicMock)
	def test_valid_customer_proceeds_to_coupon_lookup(self, mock_db):
		mock_db.table_exists.return_value = True
		mock_db.get_value.return_value = None  # coupon not found

		result = validate_coupon(coupon_code="SAVE10", company="Test Company", customer="Customer A")

		self.assertFalse(result["valid"])
		self.assertEqual(result["message"], "Invalid coupon code")
		mock_db.get_value.assert_any_call(
			"POS Coupon", {"coupon_code": "SAVE10", "company": "Test Company"}, ["*"], as_dict=1
		)


class TestPricingRuleAffectsItem(unittest.TestCase):
	def test_standard_discount_rules_always_affect(self):
		self.assertTrue(
			_pricing_rule_affects_item(
				{"rate_or_discount": "Discount Percentage"}, "ITEM-1"
			)
		)
		self.assertTrue(
			_pricing_rule_affects_item({"rate_or_discount": "Discount Amount"}, "ITEM-1")
		)
		self.assertTrue(_pricing_rule_affects_item({"rate_or_discount": "Rate"}, "ITEM-1"))

	def test_rate_from_price_list_without_target_list_does_not_affect(self):
		self.assertFalse(
			_pricing_rule_affects_item(
				{"rate_or_discount": "Rate from Price List", "custom_rate_from_price_list": None},
				"ITEM-1",
			)
		)

	@patch("erpnext.stock.get_item_details.get_price_list_rate_for", return_value=None)
	def test_rate_from_price_list_without_item_price_does_not_affect(self, _mock_rate):
		self.assertFalse(
			_pricing_rule_affects_item(
				{
					"rate_or_discount": "Rate from Price List",
					"custom_rate_from_price_list": "Promo List",
				},
				"ITEM-1",
				stock_uom="Nos",
			)
		)

	@patch("erpnext.stock.get_item_details.get_price_list_rate_for", return_value=42.0)
	def test_rate_from_price_list_with_item_price_affects(self, mock_rate):
		self.assertTrue(
			_pricing_rule_affects_item(
				{
					"rate_or_discount": "Rate from Price List",
					"custom_rate_from_price_list": "Promo List",
				},
				"ITEM-1",
				stock_uom="Nos",
			)
		)
		mock_rate.assert_called_once()
		ctx = mock_rate.call_args.args[0]
		self.assertEqual(ctx.price_list, "Promo List")
		self.assertEqual(ctx.uom, "Nos")
		self.assertEqual(mock_rate.call_args.args[1], "ITEM-1")


class TestItemHasActivePromotion(unittest.TestCase):
	@patch("pos_next.api.offers._pricing_rule_affects_item", return_value=False)
	@patch("pos_next.api.offers.frappe.db", new_callable=MagicMock)
	def test_matching_rate_from_price_list_without_effect_is_not_promotion(
		self, mock_db, mock_affects
	):
		mock_db.get_value.return_value = MagicMock(
			item_group="Products", brand=None, stock_uom="Nos"
		)
		mock_db.has_column.return_value = True
		mock_db.sql.return_value = [
			{
				"name": "PR-PROMO",
				"rate_or_discount": "Rate from Price List",
				"custom_rate_from_price_list": "Promo List",
			}
		]

		result = item_has_active_promotion("ITEM-1", company="Test Co", qty=1)

		self.assertEqual(result, {"has_promotion": False})
		mock_affects.assert_called_once()

	@patch("pos_next.api.offers._pricing_rule_affects_item", side_effect=[False, True])
	@patch("pos_next.api.offers.frappe.db", new_callable=MagicMock)
	def test_falls_through_to_next_rule_that_affects(self, mock_db, mock_affects):
		mock_db.get_value.return_value = MagicMock(
			item_group="Products", brand=None, stock_uom="Nos"
		)
		mock_db.has_column.return_value = True
		mock_db.sql.return_value = [
			{
				"name": "PR-EMPTY",
				"rate_or_discount": "Rate from Price List",
				"custom_rate_from_price_list": "Promo List",
			},
			{"name": "PR-PCT", "rate_or_discount": "Discount Percentage"},
		]

		result = item_has_active_promotion("ITEM-1", company="Test Co", qty=1)

		self.assertEqual(result, {"has_promotion": True})
		self.assertEqual(mock_affects.call_count, 2)

	@patch("pos_next.api.offers.frappe.db", new_callable=MagicMock)
	def test_missing_item_returns_false(self, mock_db):
		mock_db.get_value.return_value = None

		result = item_has_active_promotion("MISSING", company="Test Co", qty=1)

		self.assertEqual(result, {"has_promotion": False})
		mock_db.sql.assert_not_called()
