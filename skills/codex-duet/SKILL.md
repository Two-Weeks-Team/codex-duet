---
name: "codex-duet"
description: "Manage the pinned, filtered Codex and Claude skills used inside Orca: inspect selections, install profiles, preserve local modifications as overlays, review source updates, and remove owned installations. Use for Codex Duet skill maintenance."
---

# Codex Duet

Manage skills with the Codex Duet checkout recorded in the `checkout` field of
`~/.local/state/codex-duet/installations.json`. Run `python3 duet.py` from that
checkout. If the checkout is missing, report it and recover the intended checkout
before changing installed files.

For inspection, run `list`, `status --agent codex`, or
`doctor --agent claude-code`. Use `plan --profile NAME --agent AGENT` before
`install` to inspect the exact filtered selection. Default to Codex; install to
Claude only when that is the intended target. Preserve the current request's
authorization scope.

Upstream checkouts are immutable inputs. Keep changes in tracked overlays using
`file-info --skill ID --file RELATIVE` before editing an external copy, then
`override --skill ID --file RELATIVE --from EDITED_FILE --base-sha SAVED_PRE_EDIT_SHA`, or capture an owned
installed edit with `capture --skill ID --file RELATIVE --agent AGENT`. Reapply
the selected profile to adopt the overlay. Never discard local edits to make an
update pass.

Capture rejects a stale installed base, including edits made in another agent
before a newer shared overlay. Rebase against the current payload. For a new
upstream pin, pass an explicitly rebased file with `pin --rebase-file ID RELATIVE
EDITED_FILE`; do not force the old overlay over the new source.
Managed installation files must use capture. Never obtain a fresh effective
hash after a stale-edit error and claim it was the base of an older edit.

For source upgrades, read `docs/maintenance.md`. Pins are full commits, not branch
names. Review the upstream diff, license changes, filtered resources and overlay
base conflicts. A new pin does not install or expand a selection. Do not use
`git submodule update --remote` as a deployment operation.

Remove only named selections with `remove --profile NAME --agent AGENT`.
The manager refuses modified or unmanaged installations. Its receipts establish
file ownership, not permission to modify unrelated skills or plugins.

Removal does not expand dependencies and refuses to break a retained dependent.
A retired catalog ID can still be removed through its receipt. Different
managing checkouts require `--adopt-checkout`. Use `--recover` only when recovering
an exact reviewed installation after lost receipts, never to take over local edits.

This package manages skill files. It does not launch Claude sessions, change
agent permission modes, install memory services, or turn stored observations
into agent instructions. Use Orca's own CLI and the host's collaboration policy
for peer sessions.
