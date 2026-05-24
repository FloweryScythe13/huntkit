"""
org-intel-mcp -- Organisational intelligence MCP server.

Sources (added one at a time, verified before next):
  ICIJ Offshore Leaks (Panama Papers, Paradise Papers, Pandora Papers,
                        Bahamas Leaks, Offshore Leaks)
    - icij_search : fuzzy name search via Reconciliation API
    - icij_node   : full record + connected parties via REST API

  Companies House (UK official registry)
    - ch_search   : company name search
    - ch_company  : full company profile
    - ch_officers : officer list (directors, secretaries, etc.)
    - ch_psc      : persons with significant control (beneficial ownership)

API documentation:
  ICIJ REST:            https://offshoreleaks.icij.org/api/v1/rest
  ICIJ Reconciliation:  https://offshoreleaks.icij.org/api/v1/reconcile
  ICIJ OpenAPI spec:    https://offshoreleaks.icij.org/api/v1/rest/openapi/nodes
  Companies House API:  https://developer.company-information.service.gov.uk

Required environment variables:
  CH_API_KEY — Companies House Public Data API key (free registration required).
               Get one at https://developer.company-information.service.gov.uk
"""

import json
import os

import httpx
from fastmcp import FastMCP

mcp = FastMCP(
    "org-intel",
    instructions=(
        "Organisational intelligence tools for investigations. "
        "ICIJ tools: use icij_search to check whether a person or entity appears in the ICIJ "
        "Offshore Leaks database (Panama Papers, Paradise Papers, Pandora Papers, Bahamas Leaks, "
        "Offshore Leaks); use icij_node for full record including connected officers, "
        "intermediaries, and addresses. "
        "Companies House tools (UK): use ch_search to find a UK company by name; ch_company for "
        "full profile including registered address, SIC codes, and filing status; ch_officers for "
        "the list of directors and secretaries; ch_psc for persons with significant control "
        "(beneficial ownership). Requires CH_API_KEY env var."
    ),
)

# ---------------------------------------------------------------------------
# ICIJ constants
# ---------------------------------------------------------------------------

ICIJ_RECONCILE = "https://offshoreleaks.icij.org/api/v1/reconcile"
ICIJ_REST      = "https://offshoreleaks.icij.org/api/v1/rest"

ICIJ_DATASETS = frozenset({
    "bahamas-leaks",
    "offshore-leaks",
    "panama-papers",
    "pandora-papers",
    "paradise-papers",
})

ICIJ_TYPES = {
    "officer":      "Officer",
    "entity":       "Entity",
    "intermediary": "Intermediary",
    "address":      "Address",
    "other":        "Other",
}

# ---------------------------------------------------------------------------
# Companies House constants
# ---------------------------------------------------------------------------

CH_BASE = "https://api.company-information.service.gov.uk"


# ---------------------------------------------------------------------------
# ICIJ helpers
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

    entity_links: dict = {}
    if node_type.lower() == "entity":
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
# Companies House helpers
# ---------------------------------------------------------------------------

def _ch_auth() -> httpx.BasicAuth | None:
    """Return HTTP Basic auth for CH API, or None if key is not configured."""
    key = os.environ.get("CH_API_KEY", "")
    if not key:
        return None
    return httpx.BasicAuth(key, "")


_CH_KEY_MISSING = (
    "ERROR: CH_API_KEY environment variable not set. "
    "Register for a free key at https://developer.company-information.service.gov.uk"
)


def _format_ch_address(addr: dict) -> str:
    """Format a Companies House address dict to a single comma-separated string."""
    parts = [
        addr.get("premises", ""),
        addr.get("address_line_1", ""),
        addr.get("address_line_2", ""),
        addr.get("locality", ""),
        addr.get("region", ""),
        addr.get("postal_code", ""),
        addr.get("country", ""),
    ]
    return ", ".join(p for p in parts if p)


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
# Companies House tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def ch_search(
    query: str,
    company_type: str = "",
    status: str = "",
    limit: int = 10,
) -> str:
    """Search the UK Companies House register for a company by name.

    Returns company name, number, status, type, date of creation, and registered address snippet.
    Use ch_company with the returned company_number for the full profile, and ch_officers /
    ch_psc for ownership details.

    Requires CH_API_KEY environment variable (free registration at
    https://developer.company-information.service.gov.uk).

    Args:
        query: Company name or fragment to search for (e.g. "Acme Holdings", "Smith & Co").
        company_type: Optional filter — e.g. "ltd", "plc", "llp", "limited-partnership",
                      "oversea-company". Leave empty to search all types.
        status: Optional filter — e.g. "active", "dissolved", "liquidation". Leave empty for all.
        limit: Max results to return (1-25, default 10).
    """
    auth = _ch_auth()
    if not auth:
        return _CH_KEY_MISSING

    limit = max(1, min(25, limit))

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.get(
                f"{CH_BASE}/search/companies",
                params={"q": query, "items_per_page": 25},
                auth=auth,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return "ERROR: Companies House API key invalid or unauthorised."
            return f"ERROR: Companies House API returned HTTP {e.response.status_code}"
        except httpx.RequestError as e:
            return f"ERROR: Request failed — {e}"

    items = resp.json().get("items", [])

    if company_type:
        items = [i for i in items if i.get("company_type", "").lower() == company_type.lower()]
    if status:
        items = [i for i in items if i.get("company_status", "").lower() == status.lower()]

    hits = []
    for item in items[:limit]:
        h = {
            "company_name":   item.get("company_name", ""),
            "company_number": item.get("company_number", ""),
            "company_status": item.get("company_status", ""),
            "company_type":   item.get("company_type", ""),
            "date_of_creation": item.get("date_of_creation", ""),
            "address_snippet":  item.get("address_snippet", ""),
        }
        hits.append({k: v for k, v in h.items() if v})

    return json.dumps({
        "query":   query,
        "total":   len(hits),
        "results": hits,
        "note":    "Call ch_company(company_number) for full profile, ch_officers for directors.",
    }, indent=2)


@mcp.tool()
async def ch_company(company_number: str) -> str:
    """Retrieve the full Companies House profile for a UK company.

    Returns company name, number, status, type, jurisdiction, SIC codes, registered address,
    incorporation and dissolution dates, and flags for charges and insolvency history.

    Get company numbers from ch_search. The Companies House URL is included for evidence capture.

    Args:
        company_number: Companies House registration number (e.g. "12345678", "SC123456").
    """
    auth = _ch_auth()
    if not auth:
        return _CH_KEY_MISSING

    number = company_number.upper().strip()

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.get(f"{CH_BASE}/company/{number}", auth=auth)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return f"ERROR: Company {number} not found in Companies House."
            if e.response.status_code == 401:
                return "ERROR: Companies House API key invalid or unauthorised."
            return f"ERROR: Companies House API returned HTTP {e.response.status_code}"
        except httpx.RequestError as e:
            return f"ERROR: Request failed — {e}"

    raw = resp.json()
    addr = raw.get("registered_office_address", {})

    out = {
        "company_name":         raw.get("company_name", ""),
        "company_number":       raw.get("company_number", ""),
        "company_status":       raw.get("company_status", ""),
        "type":                 raw.get("type", ""),
        "jurisdiction":         raw.get("jurisdiction", ""),
        "date_of_creation":     raw.get("date_of_creation", ""),
        "date_of_cessation":    raw.get("date_of_cessation", ""),
        "sic_codes":            raw.get("sic_codes", []),
        "registered_office":    _format_ch_address(addr),
        "has_charges":          raw.get("has_charges", False),
        "has_insolvency_history": raw.get("has_insolvency_history", False),
        "company_url":          f"https://find-and-update.company-information.service.gov.uk/company/{number}",
    }

    # Always keep the boolean flags (False is informative), strip only empty strings/None/[].
    return json.dumps(
        {k: v for k, v in out.items() if v not in ("", None, [])},
        indent=2,
    )


@mcp.tool()
async def ch_officers(
    company_number: str,
    include_resigned: bool = False,
) -> str:
    """List the officers (directors, secretaries, etc.) of a UK Companies House company.

    By default returns only active officers. Set include_resigned=True to include historical
    appointments — useful for tracing past directorships.

    Args:
        company_number: Companies House registration number (e.g. "12345678", "SC123456").
        include_resigned: If True, include officers who have resigned (default False).
    """
    auth = _ch_auth()
    if not auth:
        return _CH_KEY_MISSING

    number = company_number.upper().strip()

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.get(
                f"{CH_BASE}/company/{number}/officers",
                params={"items_per_page": 50},
                auth=auth,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return f"ERROR: Company {number} not found in Companies House."
            if e.response.status_code == 401:
                return "ERROR: Companies House API key invalid or unauthorised."
            return f"ERROR: Companies House API returned HTTP {e.response.status_code}"
        except httpx.RequestError as e:
            return f"ERROR: Request failed — {e}"

    data = resp.json()
    items = data.get("items", [])

    if not include_resigned:
        items = [i for i in items if not i.get("resigned_on")]

    officers = []
    for item in items:
        o: dict = {
            "name":               item.get("name", ""),
            "role":               item.get("officer_role", ""),
            "appointed_on":       item.get("appointed_on", ""),
            "nationality":        item.get("nationality", ""),
            "country_of_residence": item.get("country_of_residence", ""),
            "occupation":         item.get("occupation", ""),
        }
        if include_resigned and item.get("resigned_on"):
            o["resigned_on"] = item["resigned_on"]
        addr = item.get("address", {})
        if addr:
            o["address"] = _format_ch_address(addr)
        officers.append({k: v for k, v in o.items() if v})

    return json.dumps({
        "company_number":   number,
        "active_count":     data.get("active_count", 0),
        "total_results":    len(items),
        "include_resigned": include_resigned,
        "officers":         officers,
    }, indent=2)


@mcp.tool()
async def ch_psc(company_number: str) -> str:
    """List the persons with significant control (PSC) for a UK Companies House company.

    PSCs are individuals or legal entities who own or control more than 25% of shares or voting
    rights, or who otherwise exercise significant influence or control. This is the primary
    beneficial ownership register for UK companies.

    Args:
        company_number: Companies House registration number (e.g. "12345678", "SC123456").
    """
    auth = _ch_auth()
    if not auth:
        return _CH_KEY_MISSING

    number = company_number.upper().strip()

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.get(
                f"{CH_BASE}/company/{number}/persons-with-significant-control",
                params={"items_per_page": 50},
                auth=auth,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return f"ERROR: Company {number} not found in Companies House."
            if e.response.status_code == 401:
                return "ERROR: Companies House API key invalid or unauthorised."
            return f"ERROR: Companies House API returned HTTP {e.response.status_code}"
        except httpx.RequestError as e:
            return f"ERROR: Request failed — {e}"

    data = resp.json()
    items = data.get("items", [])

    pscs = []
    for item in items:
        p: dict = {
            "name":                item.get("name", ""),
            "natures_of_control":  item.get("natures_of_control", []),
            "nationality":         item.get("nationality", ""),
            "country_of_residence": item.get("country_of_residence", ""),
            "notified_on":         item.get("notified_on", ""),
        }
        if item.get("ceased_on"):
            p["ceased_on"] = item["ceased_on"]
        addr = item.get("address", {})
        if addr:
            p["address"] = _format_ch_address(addr)
        pscs.append({k: v for k, v in p.items() if v not in ("", None, [])})

    if not pscs:
        return json.dumps({
            "company_number": number,
            "total":          0,
            "pscs":           [],
            "note":           "No PSC records found — company may have exemption or be newly registered.",
        }, indent=2)

    return json.dumps({
        "company_number": number,
        "total":          len(pscs),
        "pscs":           pscs,
    }, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
