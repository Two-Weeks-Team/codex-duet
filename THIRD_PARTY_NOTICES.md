# Third-party materials

Codex Duet's original manager, installer, adapters, documentation and manager skill are
licensed under Apache-2.0. Upstream skills and runtime sources retain their own
licenses; they are not relicensed as our work.

| Submodule | License | Treatment |
| --- | --- | --- |
| [mattpocock/skills](https://github.com/mattpocock/skills) | MIT | Only catalog-allowlisted skills/resources are copied when selected. Copyright and permission notice accompany each installation. |
| [obra/superpowers](https://github.com/obra/superpowers) | MIT | The selective catalog offers one verification skill. The explicit native preset includes all 15 skills and the bootstrap, or reuses an identical existing Claude plugin. |
| [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) | Apache-2.0 | The default manager leaves it uninstalled. The explicit native preset includes its 27 skills, hooks, MCP server and a shared local runtime. |

The exact commits, license file hashes and skill file hashes are in `catalog/`.
Each selectively installed upstream skill includes `.duet/licenses/` and
`.duet/origin.json`. Native plugins retain their source license and include
`.duet-origin.json`; [native integration documentation](docs/integrations.md)
identifies the layout, manifests, hook/MCP adapters, skill overlays and exact
worker patch. Original upstream copyright and license notices are preserved.

Anthropic's document skills (docx, pdf, pptx, xlsx) are excluded because their
individual terms restrict copying, derivative works and redistribution. A
repository being public does not establish permission to redistribute it.
The `claude-supermemory` plugin is not included: no license was found in the
reviewed source tree. Do not infer its license from the separate engine repo.

Commercial cloud services, model access and trademarks have separate terms.
These notices cover the source files selected here. Optional native runtime
dependencies are installed by Bun and uv from their upstream locks/constraints
and retain their own licenses. Hosted services are not provisioned by installing
their corresponding skills.
