# org-intel-mcp

MCP server for organisational intelligence: official registries, regulatory databases,
and investigative leak databases.

## Tools

| Tool | Source | What it does |
|------|--------|-------------|
| `icij_search` | ICIJ Offshore Leaks | Fuzzy name search across 810k+ offshore nodes (Panama Papers, Paradise Papers, Pandora Papers, Bahamas Leaks, Offshore Leaks) |
| `icij_node` | ICIJ Offshore Leaks | Full record + connected officers, intermediaries, addresses for a node ID |

Additional sources (Companies House, OpenCorporates, SEC EDGAR) to be added one at a time.

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

None required. All current sources are public and unauthenticated.

## ICIJ API references

- REST API: `https://offshoreleaks.icij.org/api/v1/rest`
- Reconciliation API: `https://offshoreleaks.icij.org/api/v1/reconcile`
- OpenAPI spec: `https://offshoreleaks.icij.org/api/v1/rest/openapi/nodes`
