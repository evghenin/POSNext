# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Shape the scanner item lookup response. No Frappe import."""

from __future__ import annotations


def price_per_base_unit(uom_prices: dict | None, stock_uom: str | None) -> float | None:
	"""Price of one base (stock) unit.

	Prefer the stock UOM rate, then a price row with a blank UOM (ERPNext treats
	that as the stock UOM). A price stored only on another UOM is not the base price.
	"""
	prices = uom_prices or {}
	for key in (stock_uom, "", None):
		if key in prices and prices[key] not in (None, ""):
			try:
				return float(prices[key])
			except (TypeError, ValueError):
				return None
	return None


def uoms_with_base_conversion(stock_uom: str | None, conversions: list | None) -> list[dict]:
	"""UOMs labeled by how many base units each one contains.

	The stock UOM is first, with conversion_factor 1. Other rows come from
	UOM Conversion Detail (conversion_factor is already in stock UOM).
	"""
	rows: list[dict] = []
	seen: set[str] = set()
	base = (stock_uom or "").strip()
	if base:
		rows.append({"uom": base, "conversion_factor": 1.0})
		seen.add(base)
	for raw in conversions or []:
		uom = str((raw or {}).get("uom") or "").strip()
		if not uom or uom in seen:
			continue
		try:
			factor = float(raw.get("conversion_factor"))
		except (TypeError, ValueError):
			factor = 1.0
		rows.append({"uom": uom, "conversion_factor": factor})
		seen.add(uom)
	return rows


def not_found_payload(code: str, reason: str = "not_found") -> dict:
	return {"found": False, "code": code, "reason": reason}


def found_payload(
	*,
	code: str,
	item_code: str,
	item_name: str | None,
	image: str | None,
	stock_uom: str | None,
	uom_prices: dict | None,
	conversions: list | None,
	currency: str | None,
	matched_by: str,
	barcode_uom: str | None,
) -> dict:
	image_value = (image or "").strip() or None
	return {
		"found": True,
		"code": code,
		"item_code": item_code,
		"item_name": item_name or item_code,
		"image": image_value,
		"stock_uom": stock_uom,
		"price": price_per_base_unit(uom_prices, stock_uom),
		"currency": currency or None,
		"uoms": uoms_with_base_conversion(stock_uom, conversions),
		"matched_by": matched_by,
		"barcode_uom": barcode_uom or None,
	}
