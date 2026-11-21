# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Canonical payload hashing for command journal idempotency (stdlib only)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


# Fields that define "same command content" for idempotency checks.
# operation_id itself is the uniqueness key; these are compared via payload_hash.
IDEMPOTENCY_FIELDS = (
	"command_type",
	"session_instance_id",
	"device_id",
	"cart_generation",
	"item_code",
	"qty",
	"uom",
	"batch_id",
	"items",  # for replace/merge cart payloads
)


def canonicalize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
	"""Return a stable subset of ``payload`` used for hashing."""
	src = payload or {}
	out: dict[str, Any] = {}
	for key in IDEMPOTENCY_FIELDS:
		if key not in src:
			continue
		value = src[key]
		if key == "qty" and value is not None:
			# Normalize numeric qty so 3 and 3.0 hash the same
			try:
				value = float(value)
				if value == int(value):
					value = int(value)
			except (TypeError, ValueError):
				pass
		if key == "item_code" and isinstance(value, str):
			value = value.strip().upper()
		if key == "uom" and isinstance(value, str):
			value = value.strip()
		out[key] = value
	return out


def payload_hash(payload: dict[str, Any] | None) -> str:
	"""SHA-256 hex of canonical JSON (sorted keys, no whitespace variance)."""
	canonical = canonicalize_payload(payload)
	encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
	return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def payloads_match(existing_hash: str, payload: dict[str, Any] | None) -> bool:
	"""True when ``payload`` hashes to ``existing_hash``."""
	return bool(existing_hash) and existing_hash == payload_hash(payload)
