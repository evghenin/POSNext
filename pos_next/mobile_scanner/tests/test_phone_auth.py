# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Phone auth policy tests. No Frappe required."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from pos_next.mobile_scanner.phone_auth import (
	GUEST_USER,
	PHONE_METHODS,
	TILL_METHODS,
	link_token_user_allowed,
	phone_actor,
)


class TestPhoneActor(unittest.TestCase):
	def test_missing_session_is_guest(self):
		self.assertEqual(phone_actor(None), GUEST_USER)
		self.assertEqual(phone_actor(""), GUEST_USER)
		self.assertEqual(phone_actor("Guest"), GUEST_USER)

	def test_logged_in_user_is_preserved(self):
		self.assertEqual(phone_actor("cashier@example.com"), "cashier@example.com")


class TestLinkTokenUserAllowed(unittest.TestCase):
	def test_guest_may_use_a_token_issued_to_guest(self):
		self.assertTrue(
			link_token_user_allowed(session_user="Guest", mobile_user="Guest")
		)

	def test_guest_may_use_a_token_issued_to_a_named_user(self):
		self.assertTrue(
			link_token_user_allowed(
				session_user=None, mobile_user="scanner@example.com"
			)
		)

	def test_other_logged_in_user_cannot_use_the_token(self):
		self.assertFalse(
			link_token_user_allowed(
				session_user="other@example.com",
				mobile_user="scanner@example.com",
			)
		)

	def test_owner_and_system_manager_may_use_the_token(self):
		self.assertTrue(
			link_token_user_allowed(
				session_user="scanner@example.com",
				mobile_user="scanner@example.com",
			)
		)
		self.assertTrue(
			link_token_user_allowed(
				session_user="admin@example.com",
				mobile_user="scanner@example.com",
				is_system_manager=True,
			)
		)


class TestWhitelistGuestFlags(unittest.TestCase):
	def test_phone_methods_allow_guest_and_till_methods_do_not(self):
		source = Path(__file__).resolve().parents[2] / "api" / "mobile_scanner.py"
		tree = ast.parse(source.read_text())
		flags = {}
		for node in tree.body:
			if not isinstance(node, ast.FunctionDef):
				continue
			allow_guest = False
			for deco in node.decorator_list:
				if not isinstance(deco, ast.Call):
					continue
				func = deco.func
				name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
				if name != "whitelist":
					continue
				for kw in deco.keywords:
					if kw.arg == "allow_guest" and isinstance(kw.value, ast.Constant):
						allow_guest = bool(kw.value.value)
			if node.name in PHONE_METHODS or node.name in TILL_METHODS:
				flags[node.name] = allow_guest

		for name in PHONE_METHODS:
			self.assertIn(name, flags)
			self.assertTrue(flags[name], name)
		for name in TILL_METHODS:
			self.assertIn(name, flags)
			self.assertFalse(flags[name], name)
