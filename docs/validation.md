# Validation

Local verification on 2026-10-17 used macOS, Python 3.12 and Orca 1.4.227.

| Check | Evidence |
| --- | --- |
| Regression tests | `python3 -m unittest discover -s tests -q`: 33 passed. |
| Reviewed source payloads | `python3 duet.py verify --profile all-reviewed`: five components validated against pinned sources and exact file filters. |
| Manager skill syntax | Skill frontmatter validator passed. |
| Shell scripts | `sh -n install.sh update.sh` passed. |
| Public CLI rehearsal | `python3 tools/rehearse.py` passed using live Orca inventory and disposable Codex/Claude homes. Includes install, idempotency, capture, stale-edit conflict, sync and remove. |

Two independent Claude review rounds identified base-tracking and maintenance
defects. Their scenarios were added to regression tests. The final two findings
were addressed by routing managed installation files through capture and giving
actionable receipt-based removal instructions for retired components. Those
last changes were verified locally; do not interpret the earlier review as a
separate clean review of every subsequent line.

The final state also retains backup bytes if a rollback cannot restore them,
with a regression test that injects restoration failure. Abrupt SIGKILL or power
loss still has no durable recovery journal. Multi-agent sync is a sequence of
per-agent transactions, not a host-wide atomic transaction.

No existing global skill, agent hook or memory service was changed during these
experiments. No real model's selection of the installed manager skill was tested.
Actual agent use, Windows and remote Orca hosts remain separate validation work.

The GitHub workflow runs the regression tests, source verification and shell
syntax checks on each push/PR. Its status is available in the repository's
Actions view; a local pass alone does not establish a remote CI pass.
