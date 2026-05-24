"""
Unit tests for the ICIJ Offshore Leaks tools in org-intel server.py.
All HTTP calls are mocked — no live network required.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from server import (
    _flatten_node,
    _summarise_linked,
    _type_from_schema,
    icij_node,
    icij_search,
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
# _type_from_schema
# ---------------------------------------------------------------------------

class TestTypeFromSchema(unittest.TestCase):
    def test_extracts_last_segment(self):
        self.assertEqual(_type_from_schema("https://schema.icij.org/Entity"), "Entity")

    def test_no_slash_returns_as_is(self):
        self.assertEqual(_type_from_schema("Officer"), "Officer")

    def test_empty_string(self):
        self.assertEqual(_type_from_schema(""), "")


# ---------------------------------------------------------------------------
# _summarise_linked
# ---------------------------------------------------------------------------

class TestSummariseLinked(unittest.TestCase):
    def test_extracts_id_name_type(self):
        items = [
            {"id": 42, "schema": "https://schema.icij.org/Officer",
             "properties": {"name": "John Doe"}},
        ]
        result = _summarise_linked(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 42)
        self.assertEqual(result[0]["name"], "John Doe")
        self.assertEqual(result[0]["type"], "Officer")

    def test_empty_list(self):
        self.assertEqual(_summarise_linked([]), [])

    def test_none_treated_as_empty(self):
        self.assertEqual(_summarise_linked(None), [])

    def test_missing_properties_graceful(self):
        items = [{"id": 1, "schema": "Entity", "properties": {}}]
        result = _summarise_linked(items)
        self.assertEqual(result[0]["name"], "")


# ---------------------------------------------------------------------------
# _flatten_node
# ---------------------------------------------------------------------------

class TestFlattenNode(unittest.TestCase):
    def _make_officer(self, **overrides):
        base = {
            "id": 10001,
            "schema": "https://schema.icij.org/Officer",
            "properties": {
                "name": "Jane Smith",
                "data_source": "panama-papers",
                "country_codes": ["GBR"],
                "icij_id": "abc123",
            },
        }
        base.update(overrides)
        return base

    def _make_entity(self, officers=None, intermediaries=None, addresses=None):
        return {
            "id": 20002,
            "schema": "https://schema.icij.org/Entity",
            "properties": {
                "name": "Shell Corp Ltd",
                "data_source": "paradise-papers",
                "country_codes": ["VGB"],
                "jurisdiction": "British Virgin Islands",
                "status": "Active",
                "incorporation_date": "2005-03-14",
                "officers": officers or [],
                "intermediaries": intermediaries or [],
                "addresses": addresses or [],
            },
        }

    def test_officer_node_basic_fields(self):
        result = _flatten_node(self._make_officer())
        self.assertEqual(result["id"], 10001)
        self.assertEqual(result["type"], "Officer")
        self.assertEqual(result["name"], "Jane Smith")
        self.assertEqual(result["data_source"], "panama-papers")
        self.assertIn("node_url", result)
        self.assertIn("10001", result["node_url"])

    def test_strips_empty_scalars(self):
        raw = self._make_officer()
        raw["properties"]["note"] = ""
        raw["properties"]["icij_id"] = ""
        result = _flatten_node(raw)
        self.assertNotIn("note", result)
        self.assertNotIn("icij_id", result)

    def test_entity_node_has_relationship_lists(self):
        result = _flatten_node(self._make_entity())
        # Entity relationship lists always present even when empty
        self.assertIn("officers", result)
        self.assertIn("intermediaries", result)
        self.assertIn("addresses", result)

    def test_entity_empty_relationships_preserved(self):
        result = _flatten_node(self._make_entity(officers=[], intermediaries=[], addresses=[]))
        self.assertEqual(result["officers"], [])
        self.assertEqual(result["intermediaries"], [])
        self.assertEqual(result["addresses"], [])

    def test_entity_with_connected_officer(self):
        officer_item = {
            "id": 99,
            "schema": "https://schema.icij.org/Officer",
            "properties": {"name": "Bob Builder"},
        }
        result = _flatten_node(self._make_entity(officers=[officer_item]))
        self.assertEqual(len(result["officers"]), 1)
        self.assertEqual(result["officers"][0]["name"], "Bob Builder")

    def test_entity_specific_fields_present(self):
        result = _flatten_node(self._make_entity())
        self.assertIn("jurisdiction", result)
        self.assertIn("status", result)
        self.assertIn("incorporation_date", result)

    def test_officer_does_not_have_entity_fields(self):
        result = _flatten_node(self._make_officer())
        self.assertNotIn("jurisdiction", result)
        self.assertNotIn("officers", result)

    def test_node_url_empty_when_no_id(self):
        raw = {"id": None, "schema": "Officer", "properties": {"name": "Ghost"}}
        result = _flatten_node(raw)
        self.assertNotIn("node_url", result)


# ---------------------------------------------------------------------------
# icij_search
# ---------------------------------------------------------------------------

class TestIcijSearch(unittest.IsolatedAsyncioTestCase):
    def _search_payload(self, results=None):
        return {"result": results or []}

    def _make_result(self, node_id="10001", name="Test Entity", score=90.0, match=True):
        return {
            "id": node_id,
            "name": name,
            "score": score,
            "match": match,
            "type": [{"id": "Entity", "name": "Entity"}],
        }

    async def test_returns_results_on_success(self):
        payload = self._search_payload([self._make_result()])
        with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
            result = await icij_search("Test Entity")

        data = json.loads(result)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["results"][0]["id"], "10001")
        self.assertAlmostEqual(data["results"][0]["score"], 90.0)
        self.assertIn("node_url", data["results"][0])

    async def test_no_results_returns_note(self):
        with patch("server.httpx.AsyncClient",
                   return_value=_mock_client(_mock_response(self._search_payload([])))):
            result = await icij_search("Definitely not a real name")

        data = json.loads(result)
        self.assertEqual(data["total"], 0)
        self.assertIn("note", data)
        self.assertEqual(data["dataset"], "all")

    async def test_invalid_entity_type_returns_error(self):
        result = await icij_search("Test", entity_type="banana")
        self.assertIn("ERROR", result)
        self.assertIn("entity_type", result)

    async def test_invalid_dataset_returns_error(self):
        result = await icij_search("Test", dataset="made-up-papers")
        self.assertIn("ERROR", result)
        self.assertIn("dataset", result)

    async def test_valid_dataset_uses_namespaced_url(self):
        payload = self._search_payload([self._make_result()])
        client = _mock_client(_mock_response(payload))
        with patch("server.httpx.AsyncClient", return_value=client):
            await icij_search("Test", dataset="panama-papers")

        call_args = client.post.call_args
        self.assertIn("panama-papers", call_args[0][0])

    async def test_country_code_added_to_payload(self):
        payload = self._search_payload([self._make_result()])
        client = _mock_client(_mock_response(payload))
        with patch("server.httpx.AsyncClient", return_value=client):
            await icij_search("Test", country_code="gbr")

        posted_json = client.post.call_args.kwargs.get("json") or client.post.call_args[1].get("json")
        props = posted_json.get("properties", [])
        self.assertTrue(any(p["v"] == "GBR" for p in props))

    async def test_entity_type_added_to_payload(self):
        payload = self._search_payload([self._make_result()])
        client = _mock_client(_mock_response(payload))
        with patch("server.httpx.AsyncClient", return_value=client):
            await icij_search("Test", entity_type="officer")

        posted_json = client.post.call_args.kwargs.get("json") or client.post.call_args[1].get("json")
        self.assertEqual(posted_json["type"], "Officer")

    async def test_limit_clamped_to_25(self):
        payload = self._search_payload([self._make_result() for _ in range(5)])
        client = _mock_client(_mock_response(payload))
        with patch("server.httpx.AsyncClient", return_value=client):
            await icij_search("Test", limit=100)

        posted_json = client.post.call_args.kwargs.get("json") or client.post.call_args[1].get("json")
        self.assertEqual(posted_json["limit"], 25)

    async def test_http_error_returns_error_string(self):
        with patch("server.httpx.AsyncClient",
                   return_value=_mock_client(_mock_response({}, status_code=503))):
            result = await icij_search("Test")

        self.assertIn("ERROR", result)
        self.assertIn("503", result)

    async def test_network_error_returns_error_string(self):
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(side_effect=httpx.RequestError("connection refused"))
        with patch("server.httpx.AsyncClient", return_value=client):
            result = await icij_search("Test")

        self.assertIn("ERROR", result)
        self.assertIn("Request failed", result)

    async def test_dataset_reflected_in_output(self):
        payload = self._search_payload([self._make_result()])
        with patch("server.httpx.AsyncClient", return_value=_mock_client(_mock_response(payload))):
            result = await icij_search("Test", dataset="paradise-papers")

        data = json.loads(result)
        self.assertEqual(data["dataset"], "paradise-papers")


# ---------------------------------------------------------------------------
# icij_node
# ---------------------------------------------------------------------------

class TestIcijNode(unittest.IsolatedAsyncioTestCase):
    def _entity_raw(self):
        return {
            "id": 20002,
            "schema": "https://schema.icij.org/Entity",
            "properties": {
                "name": "Shell Corp Ltd",
                "data_source": "paradise-papers",
                "country_codes": ["VGB"],
                "jurisdiction": "British Virgin Islands",
                "status": "Active",
                "incorporation_date": "2005-03-14",
                "officers": [],
                "intermediaries": [],
                "addresses": [],
            },
        }

    async def test_returns_flattened_entity(self):
        with patch("server.httpx.AsyncClient",
                   return_value=_mock_client(_mock_response(self._entity_raw()))):
            result = await icij_node(20002)

        data = json.loads(result)
        self.assertEqual(data["id"], 20002)
        self.assertEqual(data["name"], "Shell Corp Ltd")
        self.assertEqual(data["type"], "Entity")
        # Entity relationship lists always present
        self.assertIn("officers", data)

    async def test_uses_correct_endpoint(self):
        client = _mock_client(_mock_response(self._entity_raw()))
        with patch("server.httpx.AsyncClient", return_value=client):
            await icij_node(20002)

        url = client.get.call_args[0][0]
        self.assertIn("/nodes/20002", url)

    async def test_renderer_and_resolve_params_sent(self):
        client = _mock_client(_mock_response(self._entity_raw()))
        with patch("server.httpx.AsyncClient", return_value=client):
            await icij_node(20002)

        params = client.get.call_args.kwargs.get("params") or client.get.call_args[1].get("params")
        self.assertEqual(params["renderer"], "OLDB")
        self.assertEqual(params["resolve"], "true")

    async def test_404_returns_not_found_error(self):
        with patch("server.httpx.AsyncClient",
                   return_value=_mock_client(_mock_response({}, status_code=404))):
            result = await icij_node(99999)

        self.assertIn("ERROR", result)
        self.assertIn("not found", result)

    async def test_other_http_error_returns_status_code(self):
        with patch("server.httpx.AsyncClient",
                   return_value=_mock_client(_mock_response({}, status_code=500))):
            result = await icij_node(20002)

        self.assertIn("ERROR", result)
        self.assertIn("500", result)

    async def test_network_error_returns_error_string(self):
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.get = AsyncMock(side_effect=httpx.RequestError("timeout"))
        with patch("server.httpx.AsyncClient", return_value=client):
            result = await icij_node(20002)

        self.assertIn("ERROR", result)
        self.assertIn("Request failed", result)


if __name__ == "__main__":
    unittest.main()
