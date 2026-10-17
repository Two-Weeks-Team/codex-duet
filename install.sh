#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ "${1:-}" = "--preset" ]; then
  if [ "${2:-}" != "maximum" ]; then
    echo "Unknown preset. Use --preset maximum, or select --profile/--skill." >&2
    exit 1
  fi
  shift 2
  exec python3 integrations.py install "$@"
fi
if [ "$#" -eq 0 ]; then
  set -- --profile orca --agent codex
fi
exec python3 duet.py install "$@"
