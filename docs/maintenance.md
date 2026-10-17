# Maintenance

For the optional full native plugins and memory runtime, see
[native integrations](integrations.md). The commands below manage selective
file installations; their receipts are separate from native plugin receipts.

## Inspect

`list` explains profiles and source pins. `verify --profile NAME` checks the
filtered source material without an Orca connection. `plan` reads local ownership
and file conflicts without mutation. `install` additionally queries the live
Orca inventory and refuses plugin/bundle duplicates before writing files.
`doctor` validates sources and compares installed receipts with the current
catalog; it must distinguish local edits from an unapplied catalog update.

## Upgrade an upstream source

1. Fetch a specific upstream commit in its submodule, for example
   `git -C upstream/mattpocock-skills fetch origin FULL_COMMIT_SHA`.
2. Read the diff and changes to license files and the skill's referenced files.
3. Run `python3 duet.py pin --source mattpocock --rev FULL_COMMIT_SHA`.
4. Review the gitlink, source lock and exact allowlisted file hashes together.
   No files are added to a filter automatically. The command stages only the
   gitlink; commit lock/catalog/gitlink together after review and verification.
5. `verify` and `plan` the intended profiles, then reapply the selected agent.

The pin command rejects license changes and overlay base conflicts and restores
the previous pin/catalog on failure. If a selected resource moved or acquired a
new dependency, update the explicit filter after reviewing the new files.
Rebase overlays by editing against the proposed new base; do not erase a
conflict simply to get a green result. License changes require a separate source
lock and notice review; the automatic pin command deliberately cannot approve
them.

Pass each rebased file explicitly when retrying a pin:

```sh
python3 duet.py pin --source mattpocock --rev FULL_COMMIT_SHA --rebase-file matt-codebase-design SKILL.md /path/to/rebased-SKILL.md
```

The command validates every replacement against the new pin and restores the
old pin, catalog and overlay contents if validation fails. Ordinary `override`
requires `--base-sha` saved from `file-info` before editing; `capture` uses the installation's recorded
base automatically. Stale edits from a second agent or an older pin are rejected.
Override rejects source files inside a managed agent installation and directs
them to capture; it cannot substitute the current hash for that older base.

## Shared source, per-agent application

The same source/component may be selected for either agent, with independent
receipts. An overlay is shared by that component, so applying it to one agent
does not change the other agent until its own install. To maintain two different
variants, create two catalog components with distinct installed skill names
and correspondingly reviewed SKILL.md overlays. Do not install two skills with
the same name in one agent's discovery paths.

## Roll back

Check out a known good Codex Duet commit, run
`git submodule update --init --recursive`, then plan and reapply the same
selection. Ownership checks still protect local edits. The tool does not retain
the text of older installations; rollback uses the Git history of catalog,
overlays and upstream pins. Keep that history available.

After testing a rollback on a detached commit, return to your update branch
(for example `git switch main`) before using `update.sh`. The script explains
this rather than attempting a pull from a detached checkout.

Using another manager checkout requires `--adopt-checkout` explicitly; inspect
its plan first because its pins may be older. It never becomes the managing
checkout just because an agent invoked it from a temporary worktree.

After lost receipts, `install --profile NAME --agent AGENT --recover` can adopt
only a byte-for-byte match of the complete reviewed payload (including notices
and provenance). Modified, extra or missing files remain protected. Inspect
hidden `.duet-*` staging directories after an abrupt process termination;
there is no automatic crash-recovery journal.

Application stages replacements beside the destination and restores previous
directories if an ordinary filesystem/write error interrupts the transaction.
This is not a crash-recovery journal: power loss or SIGKILL during a multi-skill
transaction may require checking receipts and reapplying the intended selection.
If restoration itself fails, backup directories are retained and their paths
are reported. They are not automatically deleted to hide a rollback failure.
Do not run two different checkouts against the same home concurrently; a user
state lock serializes participating installer processes.

The installer owns only entries in its receipt. It does not delete unrelated
plugins, normalize all existing agent settings, or modify Orca projects. Empty
state directories may remain after removing skills.

`sync` preflights all previously installed selections and then reapplies each
agent under the state lock. Each agent is a separate transaction; a later I/O
failure is not a machine-wide rollback of an earlier successful agent update.
If a component has been retired from the catalog, sync preserves it and stops
before applying any skills. The error supplies the exact receipt-based remove
command. Resolve that selection (remove it explicitly or restore its catalog
entry), then retry; retirement never silently removes a skill.
