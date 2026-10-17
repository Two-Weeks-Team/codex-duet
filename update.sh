#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Commit or preserve your local changes before updating. No update was performed." >&2
  exit 1
fi
if ! git symbolic-ref --quiet HEAD >/dev/null; then
  echo "Detached checkout: return to your update branch (for example git switch main), then update." >&2
  exit 1
fi
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "Keep local edits in tracked overlays and commit them before updating." >&2
  exit 1
fi
git pull --ff-only
git submodule sync --recursive
git submodule update --init --recursive
if [ "$#" -eq 0 ]; then
  python3 duet.py sync
  exec python3 integrations.py sync
fi
exec ./install.sh "$@"
