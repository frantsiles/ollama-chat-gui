#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

uvx --from git+https://github.com/oraios/serena serena start-mcp-server --project "$PROJECT_DIR" "$@"
