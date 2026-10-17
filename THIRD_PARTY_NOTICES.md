# Third-party materials

Codex Duet's original manager, installer, documentation and manager skill are
licensed under Apache-2.0. Upstream skills and runtime sources retain their own
licenses; they are not relicensed as our work.

| Submodule | License | Treatment |
| --- | --- | --- |
| [mattpocock/skills](https://github.com/mattpocock/skills) | MIT | Only catalog-allowlisted skills/resources are copied when selected. Copyright and permission notice accompany each installation. |
| [obra/superpowers](https://github.com/obra/superpowers) | MIT | One optional verification skill is cataloged; the framework bootstrap is not installed. |
| [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) | Apache-2.0 | Pinned reference only. No worker, hook, SDK, model call or memory service is installed by this manager. |

The exact commits, license file hashes and skill file hashes are in `catalog/`.
Each installed upstream skill includes `.duet/licenses/` and `.duet/origin.json`.
Overlay modifications are identified in that origin record.

Anthropic's document skills (docx, pdf, pptx, xlsx) are excluded because their
individual terms restrict copying, derivative works and redistribution. A
repository being public does not establish permission to redistribute it.
The `claude-supermemory` plugin is not included: no license was found in the
reviewed source tree. Do not infer its license from the separate engine repo.

Commercial cloud services, model access and trademarks have separate terms.
These notices cover the files selected here, not all transitive dependencies of
optional future services. This release does not install those services.
