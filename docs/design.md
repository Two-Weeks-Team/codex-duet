# Design decisions

## Purpose

Manage Codex and Claude skill files used inside Orca. Codex is the primary
operator. Orca continues to own projects, terminals and peer coordination.
This repository is a maintained, selective integration rather than a second
workflow scheduler or a new memory engine.

## Pin, filter, overlay, apply

Git submodules preserve original source and license history. A full commit in
the source lock must equal the checked-out source and Git index gitlink. A
source cannot be dirty. The lock records both root distribution notices and
the complete inventory of license-named files, so adding a nested license
forces review even when no selected skill has otherwise changed.

A component's exact files and content hashes are an allowlist. Profiles select
components; `requires` closes reviewed component dependencies. Relative Markdown
resource links outside code examples must resolve inside that materialized
component. This is a useful resource check, not a complete semantic analysis of
references hidden in scripts, shell strings or natural language.

Overlays replace already-allowlisted files and record the base hash. They do
not change upstream source. Missing resources, a changed base or unreviewed
overlay bytes stop an update. Separate catalog components are required when
the two agents need distinct variants.

Installation copies only reviewed payloads and their notices. Upstream roots
are never symlinked into discovery directories. A content receipt identifies
what the manager owns. Unknown or changed files cannot be discarded to make
an install or remove succeed. An explicit capture records local edits as a
tracked overlay before they are adopted.

## Updates

There are two updates. Maintainers update source pins and filters in this
repository. Operators update to an approved repository commit and reapply
their already-selected components. Neither follows upstream branches at
installation time. An explicit pin operation stages only its gitlink and
requires reviewing/committing catalog and lock together.

Normal exceptions during an agent's installation restore the previous skill
directories. A process crash/power loss is outside this transaction's promise;
there is no durable crash recovery journal yet. Per-agent transactions are
independent. The next release can add a journal if actual operational evidence
justifies the extra state machine.

## License and packaging

Original code is Apache-2.0. Reused files retain upstream terms. Public source,
submodule pointers and an OS user's ability to install a package are distinct
from permission to copy/relicense its contents. Excluded restricted skills
are neither bundled nor automatically fetched by this tool.

The default file profiles do not include a memory runtime. The opt-in maximum
preset uses the separate native adapter in `integrations.py`, with exact bundle
filters, executable modes, native cache receipts, configuration snapshots and
a shared runtime outside the pinned sources. See [integrations](integrations.md).
Native plugins expose the complete upstream skill set without changing the
small default. Runtime health, model compression and agent hook activation
remain separate validation layers.
