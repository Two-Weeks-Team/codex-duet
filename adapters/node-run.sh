#!/bin/sh
set -eu
if command -v node >/dev/null 2>&1; then
  exec node "$@"
fi
for candidate in /opt/homebrew/bin/node /usr/local/bin/node "$HOME/.local/bin/node"; do
  if [ -x "$candidate" ]; then
    exec "$candidate" "$@"
  fi
done
echo "Codex Duet: Node >=20.12 is missing; repair the runtime PATH." >&2
exit 127
