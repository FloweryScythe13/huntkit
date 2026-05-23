"""
org-intel-mcp -- Organisational intelligence MCP server.

Sources (added one at a time, verified before next):
  ICIJ Offshore Leaks (Panama Papers, Paradise Papers, Pandora Papers,
                        Bahamas Leaks, Offshore Leaks)
    - icij_search : fuzzy name search via Reconciliation API
    - icij_node   : full record + connected parties via REST API

API documentation:
  REST:            https://offshoreleaks.icij.org/api/v1/rest
  Reconciliation:  https://offshoreleaks.icij.org/api/v1/reconcile
  OpenAPI spec:    https://offshoreleaks.icij.org/api/v1/rest/openapi/nodes

No API key required — all endpoints are public.
"""

import json

import httpx
from fastmcp import FastMCP

mcp = FastMCP(
    "org-intel",
    instructions=(
        "Organisational intelligence tools for investigations. "
        "Use icij_search to check whether a person or entity appears in the ICIJ Offshore Leaks "
        "database (Panama Papers, Paradise Papers, Pandora Papers, Bahamas Leaks, Offshore Leaks). "
        "Use icij_node to retrieve the full record—connected officers, intermediaries, addresses—"
        "for any node ID returned by icij_search."
    ),
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ICIJ_RECONCILE = "https://offshoreleaks.icij.org/api/v1/reconcile"
ICIJ_REST      = "https://offshoreleaks.icij.org/api/v1/rest"

# Namespaced reconciliation endpoints (dataset slugs accepted by ICIJ)
ICIJ_DATASETS = frozenset({
    "bahamas-leaks",
    "offshore-leaks",
    "panama-papers",
    "pandora-papers",
    "paradise-papers",
})

# Short type names accepted by the Reconciliation API
ICIJ_TYPES = {
    "officer":      "Officer",
    "entity":       "Entity",
    "intermediary": "Intermediary",
    "address":      "Address",
    "other":        "Other",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _type_from_schema(schema: str) -> str:
    """Extract short type name from an OLDB schema URI."""
    return schema.rsplit("/", 1)[-1] if "/" in schema else schema


def _summarise_linked(items: list) -> list:
    """Return id + name + type for a list of linked OLDB nodes."""
    out = []
    for item in (items or []):
        props = item.get("properties", {})
        out.append({
            "id":   item.get("id"),
            "name": props.get("name", ""),
            "type": _type_from_schema(item.get("schema", "")),
        })
    return out


def _flatten_node(raw: dict) -> dict:
    """Convert an OLDB node response to a clean, flat summary dict."""
    node_id   = raw.get("id")
    node_type = _type_from_schema(raw.get("schema", ""))
    props     = raw.get("properties", {})

    out: dict = {
        "id":            node_id,
        "type":          node_type,
        "name":          props.get("name", ""),
        "data_source":   props.get("data_source", ""),
        "country_codes": props.get("country_codes", []),
        "icij_id":       props.get("icij_id", ""),
        "note":          props.get("note", ""),
        "valid_until":   props.get("valid_until", ""),
        "node_url":      f"https://offshoreleaks.icij.org/nodes/{node_id}" if node_id else "",
    }

    # Entity-specific fields
    entity_links: dict = {}
    if node_type == "entity":
        out.update({
            "jurisdiction":       props.get("jurisdiction", ""),
            "status":             props.get("status", ""),
            "incorporation_date": props.get("incorporation_date", ""),
            "dissolution_date":   props.get("dissolution_date", ""),
            "ibc_ruc":            props.get("ibc_ruc", ""),
        })
        # Keep relationship lists even when empty — absence of connections is meaningful.
        entity_links = {
            "officers":       _summarise_linked(props.get("officers", [])),
            "intermediaries": _summarise_linked(props.get("intermediaries", [])),
            "addresses":      _summarise_linked(props.get("addresses", [])),
        }

    # Drop empty/null scalar values; entity relationship lists are added separately and
    # kept even when empty (an empty list signals "checked, no connections found").
    cleaned = {k: v for k, v in out.items() if v not in ("", None, [])}
    cleaned.update(entity_links)
    return cleaned


# ---------------------------------------------------------------------------
# ICIJ Offshore Leaks tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def icij_search(
    query: str,
    entity_type: str = "",
    dataset: str = "",
    country_code: str = "",
    limit: int = 10,
) -> str:
    """Search the ICIJ Offshore Leaks database for a person or entity by name.

    Uses the Reconciliation API for fuzzy name matching across 810,000+ offshore nodes spanning
    Panama Papers, Paradise Papers, Pandora Papers, Bahamas Leaks, and Offshore Leaks.

    Each result includes a relevance score (0-100). Scores above ~80 are strong matches; below
    ~40 are weak. Use icij_node with a result ID to retrieve the full record including connected
    officers, intermediaries, and addresses.

    Args:
        query: Name to search for (e.g. "John Smith", "Mossack Fonseca & Co").
        entity_type: Filter by node type — one of: officer, entity, intermediary, address, other.
                     Leave empty to search all types (recommended for initial sweeps).
        dataset: Restrict to one investigation — one of: bahamas-leaks, offshore-leaks,
                 panama-papers, pandora-papers, paradise-papers. Leave empty for all datasets.
        country_code: ISO 3166-1 alpha-3 country filter applied as a property hint
                      (e.g. "GBR", "FRA", "CHN"). Optional.
        limit: Max results to return (1-25, default 10).
    """
    limit = max(1, min(25, limit))

    # Validate optional filters
    if entity_type:
        et = entity_type.lower()
        if et not in ICIJ_TYPES:
            return f'ERROR: entity_type must be one of: {", ".join(sorted(ICIJ_TYPES))}'
        type_param = ICIJ_TYPES[et]
    else:
        type_param = None

    if dataset:
        ds = dataset.lower()
        if ds not in ICIJ_DATASETS:
            return f'ERROR: dataset must be one of: {", ".join(sorted(ICIJ_DATASETS))}'
        url = f"{ICIJ_RECONCILE}/{ds}"
    else:
        url = ICIJ_RECONCILE

    # Build Reconciliation API query payload
    payload: dict = {"query": query, "limit": limit}
    if type_param:
        payload["type"] = type_param
    if country_code:
        payload["properties"] = [{"pid": "country_codes", "v": country_code.upper()}]

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return f"ERROR: ICIJ API returned HTTP {e.response.status_code}"
        except httpx.RequestError as e:
            return f"ERROR: Request failed — {e}"

    data = resp.json()
    results = data.get("result", [])

    if not results:
        return json.dumps({
            "query":   query,
            "dataset": dataset or "all",
            "total":   0,
            "results": [],
            "note":    "No matches in ICIJ Offshore Leaks database — absence is itself evidence.",
        }, indent=2)

    hits = []
    for r in results[:limit]:
        node_id    = r.get("id", "")
        type_list  = r.get("type", [])
        type_name  = type_list[0].get("name", "") if type_list else ""
        hits.append({
            "id":       node_id,
            "name":     r.get("name", ""),
            "type":     type_name,
            "score":    round(float(r.get("score", 0)), 1),
            "match":    r.get("match", False),
            "node_url": f"https://offshoreleaks.icij.org/nodes/{node_id}" if node_id else "",
        })

    return json.dumps({
        "query":   query,
        "dataset": dataset or "all",
        "total":   len(hits),
        "results": hits,
        "note":    "Call icij_node(id) for full details and connected parties on any result.",
    }, indent=2)


@mcp.tool()
async def icij_node(node_id: int) -> str:
    """Retrieve the full record for a node in the ICIJ Offshore Leaks database.

    Returns name, type, data source (which leak dataset), country codes, and — for entities —
    the complete list of connected officers, intermediaries, and registered addresses with
    their IDs and names.

    Get node IDs from icij_search results. The node URL is also included for evidence capture.

    Args:
        node_id: Integer node ID from an icij_search result (e.g. 10067217).
    """
    url = f"{ICIJ_REST}/nodes/{node_id}"

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.get(url, params={"renderer": "OLDB", "resolve": "true"})
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return f"ERROR: Node {node_id} not found in ICIJ database."
            return f"ERROR: ICIJ API returned HTTP {e.response.status_code}"
        except httpx.RequestError as e:
            return f"ERROR: Request failed — {e}"

    raw = resp.json()
    return json.dumps(_flatten_node(raw), indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
