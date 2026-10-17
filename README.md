# Codex Duet

**Pinned, selective skill management for Codex and Claude inside Orca.**

Codex is the primary agent; Claude is a collaborator. Codex Duet manages their
skill files without taking over Orca's session or task orchestration.

원본은 submodule로 핀하고, 필요한 파일만 선택 적용하며, 수정은 overlay로
보관합니다. 설치·수정·갱신·제거를 같은 카탈로그와 파일 소유 기록으로 관리합니다.

## Install in Orca

Run on the same host and OS user as your Orca agents. Requires Python 3.10+,
Git and a running Orca with `skills installed --json`. Initial support is macOS
and Linux; Windows is not yet validated. The default file manager has no
third-party Python or Node dependencies. The optional native preset has the
additional requirements listed in [native integrations](docs/integrations.md).

```sh
git clone --recurse-submodules https://github.com/Two-Weeks-Team/codex-duet.git ~/.local/share/codex-duet
cd ~/.local/share/codex-duet
./install.sh
```

The default installs **only the `codex-duet` manager skill into Codex**. It
does not install a complete upstream framework, launch Claude, change hooks,
or start memory services. Upstream clones are inputs, not installed skills.

```sh
# Inspect the catalog and exact proposed changes
python3 duet.py list
python3 duet.py plan --profile design --agent codex

# Select skills for a particular agent
./install.sh --profile design --agent codex
./install.sh --profile orca --agent claude-code

# Inspect local modifications and the live Orca inventory
python3 duet.py status --agent codex
python3 duet.py doctor --agent codex
```

To explicitly expose **all 80 upstream skills** and prepare a shared local
memory runtime for both agents, use the opt-in native preset:

```sh
python3 integrations.py plan
./install.sh --preset maximum --provider claude
python3 integrations.py memory-start
```

This uses an existing Claude subscription for memory compression. `--provider
codex` selects an existing Codex ChatGPT login instead. Existing same-pin
Superpowers on Claude is reused. See [native integrations](docs/integrations.md)
for hook activation, all features, configuration, updates and removal.
The [feature catalog](docs/features.md) lists all 80 skills and optional service requirements.

Codex targets the shared Agent Skills path `~/.agents/skills`; other compatible
tools may also discover it. Claude targets `~/.claude/skills`. Existing
unmanaged skills, legacy Codex duplicates and Orca plugin/bundle duplicates are
refused. No existing skill or plugin is disabled automatically.

## Three independent layers

1. **Source pins:** `upstream/` Git submodules plus `catalog/sources.lock.json`
   agree on full commit SHAs. Dirty sources and mismatched gitlinks fail.
2. **Filters:** `catalog/skills.json` lists exact files, hashes, dependencies,
   installed names and profiles. No wildcard copying. New upstream files are
   never adopted automatically. Missing linked resources fail validation.
3. **Application:** selected files and tracked overlays are materialized for
   one agent, with license copies, provenance and a content receipt. A new pin
   does not change installed skills until a separate install.

Profiles are additive; selecting `design` does not silently uninstall other
profiles. Removal is explicit. Dependencies are included and shown in plans.

## Edit without losing changes

```sh
# Before editing an external working copy, record its current effective base
python3 duet.py file-info --skill matt-codebase-design --file SKILL.md
# Edit a copy of that payload, then supply the base saved BEFORE the edit
python3 duet.py override --skill matt-codebase-design --file SKILL.md --from /path/to/edited-SKILL.md --base-sha SAVED_PRE_EDIT_SHA256

# Or capture a file edited in an installation owned by Codex Duet
python3 duet.py capture --skill matt-codebase-design --file SKILL.md --agent codex

# Apply that selection again; the upstream submodule remains untouched
./install.sh --skill matt-codebase-design --agent codex
```

Overlays record both their own hash and the original file hash. If the base
changes at a new pin, the update stops for review. Local installed edits are
not accepted against a newer catalog or another agent's newer overlay: capture
checks the installation's recorded base. Rebase conflicts explicitly rather
than replacing them. Commit catalog and overlays to preserve changes.
Files inside a managed agent installation must use `capture`; `override` cannot
be used to bypass that installation's recorded edit base. Do not fetch a fresh
hash after a stale-capture error and apply it to an old working copy.

## Update and remove

```sh
# Consume commits approved in this repository, including pinned gitlinks
./update.sh

# To update a selected non-default profile on an agent
./update.sh --profile design --agent codex

# Remove only clean installations owned by this manager
python3 duet.py remove --profile design --agent codex
```

`update.sh` requires a clean checkout, fast-forwards this repo, checks out its
submodule pins, and reapplies the skills already owned on both agents, including
their reviewed dependency closure. Pass an explicit profile/agent to update
only that selection. It does not track upstream branches. `doctor` reports
unapplied catalog changes separately from local file edits.
For maintainer pin upgrades, rollback and license review, see
[maintenance](docs/maintenance.md).

Removal does not expand dependencies. It retains shared dependencies and refuses
to remove a dependency still required by a retained installation. A retired
catalog component can still be removed by its ID using its ownership receipt.

## Scope and status

This is an early implementation. Local tests cover filtering, pins, overlays,
ownership, conflicts and rollback. See CI for the current test result. End-to-end
skill selection by real Codex/Claude models, Windows and remote Orca hosts require
separate validation. Installing a file does not prove that an agent used it.

The manager never executes upstream scripts. A selected skill may instruct an
agent to execute its resources during later use; review the selected files.
The default file manager does not start a memory backend. The explicit maximum
native preset has a separate memory adapter and dependency installation.

## License

Apache-2.0 for original work. MIT and Apache-2.0 upstream notices are retained.
See [third-party notices](THIRD_PARTY_NOTICES.md). Codex Duet is an independent
community project, not an official OpenAI, Anthropic or Orca distribution.
