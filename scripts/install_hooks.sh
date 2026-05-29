#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$ROOT_DIR/.githooks"

git config core.hooksPath "$HOOKS_DIR"
chmod +x "$HOOKS_DIR/pre-commit"

echo "Git hooks installed from $HOOKS_DIR"
