# org-intel-mcp

MCP server for organisational intelligence: official registries, regulatory databases,
and investigative leak databases.

## Tools

| Tool | Source | What it does |
|------|--------|-------------|
| `icij_search` | ICIJ Offshore Leaks | Fuzzy name search across 810k+ offshore nodes (Panama Papers, Paradise Papers, Pandora Papers, Bahamas Leaks, Offshore Leaks) |
| `icij_node` | ICIJ Offshore Leaks | Full record + connected officers, intermediaries, addresses for a node ID |
| `ch_search` | Companies House (UK) | Company name search — returns name, number, status, type, incorporation date |
| `ch_company` | Companies House (UK) | Full company profile — registered address, SIC codes, charges, insolvency history |
| `ch_officers` | Companies House (UK) | Officer list (directors, secretaries) — active only or including resigned |
| `ch_psc` | Companies House (UK) | Persons with significant control — beneficial ownership register |

Additional sources (OpenCorporates, SEC EDGAR) to be added one at a time.

## Setup

```bash
cd mcp-servers/org-intel
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run standalone

```bash
python server.py
```

## Add to Claude Code

See `.mcp.json.template` in the project root — the `org-intel` stanza is already included.

## API keys

| Source | Key required | Where to get it |
|--------|-------------|-----------------|
| ICIJ Offshore Leaks | No | Public, unauthenticated |
| Companies House | Yes (`CH_API_KEY`) | Free registration at https://developer.company-information.service.gov.uk |

## API references

### ICIJ Offshore Leaks
- REST API: `https://offshoreleaks.icij.org/api/v1/rest`
- Reconciliation API: `https://offshoreleaks.icij.org/api/v1/reconcile`
- OpenAPI spec: `https://offshoreleaks.icij.org/api/v1/rest/openapi/nodes`

### Companies House
- Base URL: `https://api.company-information.service.gov.uk`
- Auth: HTTP Basic — API key as username, empty password
- Developer portal: `https://developer.company-information.service.gov.uk`
