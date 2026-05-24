"""
Unit tests for the Companies House tools in org-intel server.py.
All HTTP calls are mocked — no live network required.
"""

import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from server import (
    _ch_auth,
    _format_ch_address,
    ch_company,
    ch_officers,
    ch_psc,
    ch_search,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _mock_client(response: MagicMock) -> MagicMock:
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(return_value=response)
    client.post = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# _ch_auth
# ---------------------------------------------------------------------------

class TestChAuth(unittest.TestCase):
    def test_returns_none_when_key_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CH_API_KEY", None)
            self.assertIsNone(_ch_auth())

    def test_returns_basic_auth_when_key_present(self):
        with patch.dict(os.environ, {"CH_API_KEY": "testapikey"}):
            auth = _ch_auth()
            self.assertIsInstance(auth, httpx.BasicAuth)


# ---------------------------------------------------------------------------
# _format_ch_address
# ---------------------------------------------------------------------------

class TestFormatChAddress(unittest.TestCase):
    def test_full_address(self):
        addr = {
            "premises": "10",
            "address_line_1": "Downing Street",
            "locality": "London",
            "postal_code": "SW1A 2AA",
            "country": "United Kingdom",
        }
        result = _format_ch_address(addr)
        self.assertEqual(result, "10, Downing Street, London, SW1A 2AA, United Kingdom")

    def test_skips_empty_parts(self):
        addr = {"address_line_1": "1 Main St", "locality": "Bristol", "postal_code": "BS1 1AA"}
        result = _format_ch_address(addr)
        self.assertEqual(result, "1 Main St, Bristol, BS1 1AA")

    def test_empty_dict(self):
        self.assertEqual(_format_ch_address({}), "")


# ---------------------------------------------------------------------------
# ch_search
# ---------------------------------------------------------------------------

class TestChSearch(unittest.IsolatedAsyncioTestCase):
    async def test_returns_error_when_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CH_API_KEY", None)
            result = await ch_search("Acme")
        self.assertIn("CH_API_KEY", result)

    async def test_returns_results_on_success(self):
        payload = {
            "items": [
                {
                    "company_name": "ACME LIMITED",
                    "company_number": "12345678",
                    "company_status": "active",
                    "company_type": "ltd",
                    "date_of_creation": "2010-01-15",
                    "address_snippet": "1 Main St, London, EC1A 1BB",
                }
            ]
        }
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
                result = await ch_search("Acme")

        data = json.loads(result)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["results"][0]["company_number"], "12345678")
        self.assertEqual(data["results"][0]["company_name"], "ACME LIMITED")

    async def test_filters_by_company_type(self):
        payload = {
            "items": [
                {"company_name": "ACME LTD", "company_number": "11111111",
                 "company_type": "ltd", "company_status": "active"},
                {"company_name": "ACME PLC", "company_number": "22222222",
                 "company_type": "plc", "company_status": "active"},
            ]
        }
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
                result = await ch_search("Acme", company_type="ltd")

        data = json.loads(result)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["results"][0]["company_number"], "11111111")

    async def test_filters_by_status(self):
        payload = {
            "items": [
                {"company_name": "ACME LTD", "company_number": "11111111",
                 "company_type": "ltd", "company_status": "active"},
                {"company_name": "OLD ACME LTD", "company_number": "00000001",
                 "company_type": "ltd", "company_status": "dissolved"},
            ]
        }
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
                result = await ch_search("Acme", status="dissolved")

        data = json.loads(result)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["results"][0]["company_number"], "00000001")

    async def test_empty_results(self):
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient",
                       return_value=_mock_client(_mock_response({"items": []}))):
                result = await ch_search("Zzzznonexistent")

        data = json.loads(result)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["results"], [])

    async def test_http_401_returns_error(self):
        with patch.dict(os.environ, {"CH_API_KEY": "badkey"}):
            with patch("server.httpx.AsyncClient",
                       return_value=_mock_client(_mock_response({}, status_code=401))):
                result = await ch_search("Acme")

        self.assertIn("ERROR", result)
        self.assertIn("invalid or unauthorised", result)

    async def test_http_500_returns_error(self):
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient",
                       return_value=_mock_client(_mock_response({}, status_code=500))):
                result = await ch_search("Acme")

        self.assertIn("ERROR", result)
        self.assertIn("500", result)


# ---------------------------------------------------------------------------
# ch_company
# ---------------------------------------------------------------------------

class TestChCompany(unittest.IsolatedAsyncioTestCase):
    async def test_returns_error_when_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CH_API_KEY", None)
            result = await ch_company("12345678")
        self.assertIn("CH_API_KEY", result)

    async def test_returns_profile_on_success(self):
        payload = {
            "company_name": "ACME LIMITED",
            "company_number": "12345678",
            "company_status": "active",
            "type": "ltd",
            "jurisdiction": "england-wales",
            "date_of_creation": "2010-01-15",
            "sic_codes": ["74909"],
            "registered_office_address": {
                "address_line_1": "1 Main Street",
                "locality": "London",
                "postal_code": "EC1A 1BB",
            },
            "has_charges": True,
            "has_insolvency_history": False,
        }
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
                result = await ch_company("12345678")

        data = json.loads(result)
        self.assertEqual(data["company_name"], "ACME LIMITED")
        self.assertEqual(data["company_number"], "12345678")
        self.assertEqual(data["registered_office"], "1 Main Street, London, EC1A 1BB")
        self.assertEqual(data["sic_codes"], ["74909"])
        self.assertTrue(data["has_charges"])
        self.assertIn("company_url", data)
        self.assertIn("12345678", data["company_url"])

    def test_company_number_uppercased(self):
        # Verify normalisation — lower-case input is uppercased before URL construction.
        # We just check the URL is correct by calling with lowercase.
        import asyncio
        payload = {
            "company_name": "SCOTS LTD",
            "company_number": "SC123456",
            "company_status": "active",
            "type": "ltd",
        }
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            client = _mock_client(_mock_response(payload))
            with patch("server.httpx.AsyncClient", return_value=client):
                asyncio.run(ch_company("sc123456"))

        call_args = client.get.call_args
        self.assertIn("SC123456", call_args[0][0])

    async def test_not_found_returns_error(self):
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient",
                       return_value=_mock_client(_mock_response({}, status_code=404))):
                result = await ch_company("99999999")

        self.assertIn("ERROR", result)
        self.assertIn("not found", result)

    async def test_false_booleans_preserved(self):
        payload = {
            "company_name": "BORING LTD",
            "company_number": "00000001",
            "company_status": "active",
            "has_charges": False,
            "has_insolvency_history": False,
        }
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
                result = await ch_company("00000001")

        data = json.loads(result)
        # False booleans should be in the output (not stripped)
        self.assertIn("has_charges", data)
        self.assertFalse(data["has_charges"])


# ---------------------------------------------------------------------------
# ch_officers
# ---------------------------------------------------------------------------

class TestChOfficers(unittest.IsolatedAsyncioTestCase):
    async def test_returns_error_when_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CH_API_KEY", None)
            result = await ch_officers("12345678")
        self.assertIn("CH_API_KEY", result)

    async def test_active_officers_only_by_default(self):
        payload = {
            "active_count": 1,
            "items": [
                {"name": "SMITH, John", "officer_role": "director",
                 "appointed_on": "2015-03-01", "nationality": "British"},
                {"name": "DOE, Jane", "officer_role": "director",
                 "appointed_on": "2010-01-01", "resigned_on": "2018-06-30"},
            ],
        }
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
                result = await ch_officers("12345678")

        data = json.loads(result)
        self.assertEqual(data["total_results"], 1)
        self.assertEqual(data["officers"][0]["name"], "SMITH, John")
        self.assertFalse(data["include_resigned"])

    async def test_include_resigned(self):
        payload = {
            "active_count": 1,
            "items": [
                {"name": "SMITH, John", "officer_role": "director",
                 "appointed_on": "2015-03-01"},
                {"name": "DOE, Jane", "officer_role": "director",
                 "appointed_on": "2010-01-01", "resigned_on": "2018-06-30"},
            ],
        }
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
                result = await ch_officers("12345678", include_resigned=True)

        data = json.loads(result)
        self.assertEqual(data["total_results"], 2)
        self.assertTrue(data["include_resigned"])
        resigned = next(o for o in data["officers"] if o["name"] == "DOE, Jane")
        self.assertEqual(resigned["resigned_on"], "2018-06-30")

    async def test_not_found_returns_error(self):
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient",
                       return_value=_mock_client(_mock_response({}, status_code=404))):
                result = await ch_officers("99999999")

        self.assertIn("ERROR", result)
        self.assertIn("not found", result)

    async def test_address_formatted_in_officer(self):
        payload = {
            "active_count": 1,
            "items": [
                {
                    "name": "JONES, Bob",
                    "officer_role": "secretary",
                    "appointed_on": "2020-01-01",
                    "address": {
                        "address_line_1": "5 Baker Street",
                        "locality": "London",
                        "postal_code": "W1U 8EW",
                    },
                }
            ],
        }
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
                result = await ch_officers("12345678")

        data = json.loads(result)
        self.assertIn("address", data["officers"][0])
        self.assertEqual(data["officers"][0]["address"], "5 Baker Street, London, W1U 8EW")


# ---------------------------------------------------------------------------
# ch_psc
# ---------------------------------------------------------------------------

class TestChPsc(unittest.IsolatedAsyncioTestCase):
    async def test_returns_error_when_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CH_API_KEY", None)
            result = await ch_psc("12345678")
        self.assertIn("CH_API_KEY", result)

    async def test_returns_psc_list(self):
        payload = {
            "items": [
                {
                    "name": "BLOGGS, Joseph Frederick",
                    "natures_of_control": [
                        "ownership-of-shares-75-to-100-percent"
                    ],
                    "nationality": "British",
                    "country_of_residence": "England",
                    "notified_on": "2016-04-06",
                    "address": {
                        "address_line_1": "1 High Street",
                        "locality": "Manchester",
                        "postal_code": "M1 1AE",
                    },
                }
            ]
        }
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
                result = await ch_psc("12345678")

        data = json.loads(result)
        self.assertEqual(data["total"], 1)
        psc = data["pscs"][0]
        self.assertEqual(psc["name"], "BLOGGS, Joseph Frederick")
        self.assertIn("ownership-of-shares-75-to-100-percent", psc["natures_of_control"])
        self.assertEqual(psc["address"], "1 High Street, Manchester, M1 1AE")

    async def test_ceased_psc_included(self):
        payload = {
            "items": [
                {
                    "name": "OLD OWNER LTD",
                    "natures_of_control": ["ownership-of-shares-25-to-50-percent"],
                    "notified_on": "2016-04-06",
                    "ceased_on": "2020-03-01",
                }
            ]
        }
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
                result = await ch_psc("12345678")

        data = json.loads(result)
        self.assertEqual(data["pscs"][0]["ceased_on"], "2020-03-01")

    async def test_empty_pscs_returns_note(self):
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient",
                       return_value=_mock_client(_mock_response({"items": []}))):
                result = await ch_psc("12345678")

        data = json.loads(result)
        self.assertEqual(data["total"], 0)
        self.assertIn("note", data)

    async def test_not_found_returns_error(self):
        with patch.dict(os.environ, {"CH_API_KEY": "key"}):
            with patch("server.httpx.AsyncClient",
                       return_value=_mock_client(_mock_response({}, status_code=404))):
                result = await ch_psc("99999999")

        self.assertIn("ERROR", result)
        self.assertIn("not found", result)


if __name__ == "__main__":
    unittest.main()
