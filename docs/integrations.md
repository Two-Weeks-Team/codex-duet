# Full native integrations in Orca

The default installation remains the small `codex-duet` manager skill. The
explicit **maximum** preset exposes all skills in the three pinned repositories
through the agents' native plugin registries: Matt 38, Superpowers 15, and
claude-mem 27. It also prepares one shared local memory runtime. Skills are
available on demand; installing them does not execute every workflow.

Run on the same host and OS user as the Orca agents. Native validation uses
Codex CLI 0.163.0 and Claude Code 2.1.302 on macOS. Memory additionally needs
Node >=20.12, Bun >=1.1.31 and, for vector search, uv/uvx. No hosted memory
account or API key is required when using an existing agent subscription.

```sh
python3 integrations.py plan
./install.sh --preset maximum --provider claude
python3 integrations.py memory-start
python3 integrations.py status
python3 integrations.py memory-status
```

Choose `--provider claude` for an existing Claude subscription or `--provider
codex` for an existing Codex ChatGPT login. The Claude memory backend uses
headless Agent SDK processes; it does not create, clear or replace the Orca
project's shared Claude collaboration terminal. Codex remains the primary
operator. The alternative Codex observer uses isolated app-server clients.
Each backend consumes its subscription usage. `manual` preserves an already
configured API provider; provider-specific features need their own validation.

Inspect a smaller selection before applying it:

```sh
python3 integrations.py plan --bundle mattpocock --agent codex
python3 integrations.py install --bundle mattpocock --agent codex
python3 integrations.py install --bundle claude-mem --agent both --provider claude
```

An enabled Claude plugin is reused only when its recorded Git commit and its
operational files match the source pin. On the development Mac this reuses the
existing official Superpowers 7.0.0. A differently pinned plugin is a conflict.
Native plugin namespaces preserve existing user skills such as `handoff`.
Selective file installations from the same source must first be explicitly
removed before installing that source's complete plugin.

## What is adapted

`catalog/bundles.lock.json` contains exact source paths, hashes and executable
modes. No recursive wildcard is evaluated at install time. New upstream files
do not become installed merely because they appeared in a source checkout.

Matt's category folders are flattened for native discovery, including the 11
miscellaneous/in-progress skills omitted from its standard 27-skill plugin.
The maximum preset intentionally exposes these too. An Orca startup adapter
keeps worktree/session operations with Orca and preserves the single Claude
peer policy. Superpowers' Codex manifest explicitly loads its startup hook.

claude-mem's hook and MCP entrypoints use an absolute shared runtime path and a
stable Node wrapper. They do not search the current project for executable
files. Dependencies are installed once, outside the submodule and native
caches, using `bun install --frozen-lockfile`. Native memory packages omit the
dependency manifest to prevent a second automatic cache installation.

A version-bound worker patch preserves upstream Claude knowledge queries and
adds Codex corpus priming/query support when Codex is the chosen provider.
Codex queries replay the corpus and the last twelve conversation messages,
stored in the corpus JSON, through an isolated text-only app-server client.
The patch checks the complete base hash, replaced section, replacement and
complete output. A new upstream worker requires a new review, not fuzzy patching.

Local memory uses loopback only. Duet defaults to no telemetry, no fallback
provider, secret redaction, and a non-blocking file read gate. Cross-agent
startup context and semantic injection are enabled. Existing conflicting
preferences or environment overrides stop installation; credentials and
unrelated settings are preserved. Chroma's upstream runtime pins chroma-mcp
0.2.6 and chromadb 1.5.9; other transitive Python constraints are upstream's
responsibility. Cloud sync, Screenpipe, NotebookLM and release/publishing
workflows require their corresponding accounts/apps and an applicable task.
Installing their skills does not provision those external products or publish.

## Activate in a running agent

Codex requires review and trust for plugin hooks. Installing a plugin does not
trust its hooks: use `/hooks` to inspect and trust the current definitions.
Duet does not manufacture `trusted_hash` records or bypass that review.
See [OpenAI's hook documentation](https://learn.chatgpt.com/docs/hooks).

Claude Code provides `/reload-plugins` to apply plugin changes without replacing
the running session. Preserve any current prompt draft and finish the active
task before using it. See [Claude's command reference](https://code.claude.com/docs/en/commands).
File installation, native discovery, trusted hooks, MCP calls and actual model
outcomes are separate checks.

## Edit, update and remove

For a Duet-owned native cache edit, capture the exact file before updating:

```sh
python3 integrations.py capture --bundle mattpocock --agent codex --file skills/prototype/SKILL.md
python3 integrations.py install --bundle mattpocock --agent both
```

Capture records a tracked overlay in `overlays/native/` and checks the installed
baseline. An old copy from another agent cannot replace a newer overlay.
Generated manifests and hooks are maintained in the adapter rather than captured.
Modified files, extra files, changed executable modes and unmanaged plugin
registrations stop replacement/removal. Commit the overlay and lock together.

`./update.sh` consumes approved repository commits and synchronizes previously
owned file selections and native bundles. The marketplace address is stable;
payloads and runtimes are immutable versioned directories. Codex uses native
`plugin add` to upgrade; Claude refreshes only the Duet marketplace and uses
`plugin update`. Each completed registry operation is recorded. Transactions
are per native client, not atomic across both clients or an unexpected crash.
After an update that changes the runtime, run `python3 integrations.py
memory-start` to move an already-running Duet-owned worker to the new pinned
runtime. Its database stays in place. A worker belonging to another installation
is not stopped automatically.

```sh
python3 integrations.py configure-memory --provider codex
python3 integrations.py memory-restart
python3 integrations.py remove --bundle mattpocock --agent both
python3 integrations.py memory-stop
```

Private configuration snapshots and receipts live under
`~/.local/state/codex-duet`. Source-derived native packages and dependencies live
under `~/.local/share/codex-duet-managed`, outside the managing Git checkout.
Memory data lives under `~/.claude-mem`.
Removal preserves memory data, externally supplied plugins and staged rollback
payloads. It does not delete accounts, unrelated hooks or shared dependencies.
Never restore whole old settings over newer unrelated changes; inspect the
private snapshot and restore only the intended keys.

For maintainer pin upgrades, update the source pin, review bundle file hashes,
overlays, executable modes and adapters together, and run native rehearsal.
`duet.py pin` deliberately does not approve an expanded native filter.
`python3 tools/refresh_bundles.py --source SOURCE` previews changes to the
existing allowlist; `--write` applies those hashes after review. New files are
never admitted automatically. Overlay and version-bound patch conflicts stop
the refresh and require an explicit rebase/review.
