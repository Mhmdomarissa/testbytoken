"""Tests for API farm token chaining and paste normalization."""

from __future__ import annotations

import unittest

from api_farm.chain import extract_variables
from api_farm.engine import run_api_request, run_api_suite
from api_farm.normalize import normalize_request_payload, parse_postman_paste


class ApiFarmTokenTests(unittest.TestCase):
    def test_escuelajs_login_chain(self) -> None:
        variables: dict = {}
        login = {
            "name": "Login",
            "method": "POST",
            "url": "https://api.escuelajs.co/api/v1/auth/login",
            "headers": {"Content-Type": "application/json"},
            "body": '{"email":"john@mail.com","password":"changeme"}',
            "expected_status": 201,
            "extractors": [{"name": "token", "path": "access_token", "source": "json"}],
            "auth": {"type": "none"},
        }
        r1 = run_api_request(login, variables)
        self.assertEqual(r1.status, "PASS")
        self.assertIn("token", r1.extracted)

        profile = {
            "name": "Profile",
            "method": "GET",
            "url": "https://api.escuelajs.co/api/v1/auth/profile",
            "headers": {},
            "body": "",
            "expected_status": 200,
            "auth": {"type": "bearer", "token": "{{token}}"},
            "extractors": [],
        }
        r2 = run_api_request(profile, variables)
        self.assertEqual(r2.status, "PASS")

    def test_wrong_expected_status_still_extracts(self) -> None:
        variables: dict = {}
        login = {
            "name": "Login",
            "method": "POST",
            "url": "https://api.escuelajs.co/api/v1/auth/login",
            "headers": {"Content-Type": "application/json"},
            "body": '{"email":"john@mail.com","password":"changeme"}',
            "expected_status": 200,
            "extractors": [{"name": "token", "path": "access_token", "source": "json"}],
            "auth": {"type": "none"},
        }
        r1 = run_api_request(login, variables)
        self.assertEqual(r1.status, "FAIL")
        self.assertIn("token", r1.extracted)
        self.assertIn("Tip:", r1.message)

    def test_parse_postman_paste(self) -> None:
        raw = (
            'POST https://api.escuelajs.co/api/v1/auth/login'
            'Content-Type: application/json{"email":"john@mail.com","password":"changeme"}'
        )
        parsed = parse_postman_paste(raw)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["method"], "POST")
        self.assertEqual(parsed["url"], "https://api.escuelajs.co/api/v1/auth/login")
        self.assertIn("Content-Type", parsed["headers"])
        self.assertIn("email", parsed["body"])

    def test_normalize_glued_url(self) -> None:
        payload = normalize_request_payload(
            {
                "method": "GET",
                "url": (
                    "POST https://api.escuelajs.co/api/v1/auth/login"
                    'Content-Type: application/json{"email":"john@mail.com","password":"changeme"}'
                ),
                "headers": {},
                "body": "",
            }
        )
        self.assertEqual(payload["method"], "POST")
        self.assertEqual(payload["url"], "https://api.escuelajs.co/api/v1/auth/login")
        self.assertIn("email", payload["body"])

    def test_extract_fallback_access_token(self) -> None:
        variables: dict = {}
        response = {
            "body": '{"access_token":"abc123","refresh_token":"xyz"}',
            "headers": {},
            "http_status": 201,
        }
        extracted, messages = extract_variables(
            response,
            [{"name": "token", "path": "wrong.path", "source": "json"}],
            variables,
        )
        self.assertEqual(extracted.get("token"), "abc123")
        self.assertTrue(any("fallback" in m for m in messages))

    def test_suite_chain(self) -> None:
        specs = [
            {
                "name": "Login",
                "method": "POST",
                "url": "https://api.escuelajs.co/api/v1/auth/login",
                "headers": {"Content-Type": "application/json"},
                "body": '{"email":"john@mail.com","password":"changeme"}',
                "expected_status": 201,
                "extractors": [{"name": "token", "path": "access_token", "source": "json"}],
                "auth": {"type": "none"},
            },
            {
                "name": "Profile",
                "method": "GET",
                "url": "https://api.escuelajs.co/api/v1/auth/profile",
                "expected_status": 200,
                "auth": {"type": "bearer", "token": "{{token}}"},
            },
        ]
        suite = run_api_suite(specs)
        self.assertEqual(suite["summary"]["failed"], 0)
        self.assertIn("token", suite["variables"])


if __name__ == "__main__":
    unittest.main()
