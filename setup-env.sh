#!/usr/bin/env bash
# Generate .mcp.json from .mcp.json.template by substituting environment variables.
# Run this once after editing .env, and again whenever you add or change a key.
#
# Usage:
#   cp .env.example .env   # first time — fill in your keys
#   bash setup-env.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$REPO_DIR/.env"
TEMPLATE="$REPO_DIR/.mcp.json.template"
OUTPUT="$REPO_DIR/.mcp.json"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: .env not found."
  echo "Run: cp .env.example .env  — then fill in your keys."
  exit 1
fi

if ! command -v envsubst &>/dev/null; then
  echo "Error: envsubst not found. Install gettext:"
  echo "  macOS:  brew install gettext && brew link gettext --force"
  echo "  Linux:  sudo apt install gettext  (or equivalent)"
  exit 1
fi

# Export vars from .env so envsubst can see them.
# Only exports KEY=VALUE lines; skips comments and blank lines.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

envsubst < "$TEMPLATE" > "$OUTPUT"
echo "Generated $OUTPUT"
