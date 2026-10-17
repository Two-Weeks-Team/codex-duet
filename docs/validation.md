# Validation

Local verification on 2026-10-17 used macOS, Python 3.12, Orca 1.4.227,
Codex CLI 0.163.0, Claude Code 2.1.302, Node 25.9.0 and Bun 1.3.9.

| Check | Evidence |
| --- | --- |
| Regression tests | `python3 -m unittest discover -s tests -q`: 49 passed, including 16 native integration tests. |
| Selective source payloads | `python3 duet.py verify --profile all-reviewed`: five components validated against pinned sources and exact file filters. |
| Native payloads | `python3 integrations.py verify`: all three pinned bundles, adapters, overlays, runtime patch hashes and executable modes validated. |
| Manager skill syntax | Skill frontmatter validator passed. |
| Shell and adapter syntax | `sh -n install.sh update.sh adapters/node-run.sh` and `node --check adapters/claude-mem-knowledge.js` passed. |
| Selective CLI rehearsal | `python3 tools/rehearse.py`: disposable Codex/Claude homes; install, idempotency, capture, stale-edit conflict, sync and remove passed. |
| Native CLI rehearsal | `python3 tools/rehearse_native.py`: real native registration on both clients, actual Codex app-server skill discovery, captured overlay upgrade on both clients through the stable marketplace, and removal passed. No model call or memory service runs in this rehearsal. |
| Native discovery | The actual Codex loader returned Matt 38, Superpowers 15 and claude-mem 27 skills, with zero skill parsing errors in a disposable home. |
| Memory observation | Separate real Codex and Claude subscription-backed compression runs produced observations retrievable through the local HTTP API. The final selected backend is Claude. |
| Memory MCP | A real stdio MCP session initialized, listed 19 tools and found the synthetic observation through `mem_search`. |
| Code structure tools | A real MCP `smart_outline` call parsed the Python integration module and returned its class/method structure through tree-sitter. |
| Vector search and viewer | The final shared runtime returned a successful Chroma deep semantic round-trip probe and served its local viewer over HTTP. |
| Knowledge corpus | A scoped synthetic corpus was built, primed and queried through the real Claude backend. After restarting the worker, a query resumed the same stored corpus session and retrieved its facts. |

The public feature catalog lists all 80 skills. Installation and native discovery
do not establish successful completion of all 80 model workflows. Cloud sync,
Screenpipe, NotebookLM, external publishing and account-specific workflows were
not provisioned or exercised. The optional Codex knowledge adapter has not had a
real model corpus prime/query test; the Codex observation backend was tested.

The maximum preset was installed on the development Mac for both agents. All
six native selections report enabled registrations and verified files; actual
Codex discovery returned all 80 skills without parsing errors. The shared local
worker was moved to the managed runtime path with its database preserved,
initialized with the Claude provider and MCP ready. It preserves the same-pin official
Claude Superpowers plugin. Private configuration backups and test evidence stay
outside the public repository. Synthetic memory records are removed after the
live checks; normal memory data and unrelated agent settings are preserved.

Independent Claude reviews identified update-address, PATH-dependent rendering,
provider-routing, preference and partial-write defects. Those scenarios were
corrected and checked with regression tests and live native CLI rehearsal.
Review reports are snapshots of their specified file hashes, not blanket
approval of every later change.

Codex hook trust and reloading plugins in an already-running Claude session are
separate activation checks. Duet does not bypass hook trust or overwrite a
running session's input draft. Native file installation, native skill loading,
hook activation, MCP access and actual model use must be reported separately.
On the development Mac, `hooks/list` found eight enabled Duet hook definitions
without parser errors or warnings; all eight still required trust. The retained
Claude session had an existing input draft, so it was not reloaded automatically.
Windows and remote Orca hosts remain unvalidated.

Rollback preserves backup bytes when restoration fails. Abrupt SIGKILL or power
loss still has no durable recovery journal. Selective sync is a sequence of
per-agent transactions; native registration is also per client, not one atomic
transaction across the host. A partial operation is reconciled from receipts,
native registry state and preserved backups before retrying.

The GitHub workflow runs the regression tests, both source verifiers and shell
syntax checks. Native CLI loading and subscription-backed model checks above
are local evidence; CI does not run those tools or consume model subscriptions.
A local pass does not establish a remote CI pass for a new commit.
