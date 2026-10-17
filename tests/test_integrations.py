from pathlib import Path
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import duet
from integrations import Integrations


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "checkout"
        self.home = Path(self.tmp.name) / "home"
        self.root.mkdir()
        self.home.mkdir()
        source = self.root / "source"
        source.mkdir()
        content = {
            ".claude-plugin/plugin.json": json.dumps({"name": "fixture", "version": "1.0.0"}).encode(),
            ".codex-plugin/plugin.json": json.dumps({"name": "fixture", "version": "1.0.0"}).encode(),
            "skills/alpha/SKILL.md": b'---\nname: "alpha"\ndescription: "Fixture"\n---\n',
            "skills/alpha/tool.sh": b"#!/bin/sh\nexit 0\n",
            "LICENSE": b"MIT fixture\n",
        }
        files = {}
        for relative, data in content.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            files[relative] = {"from": relative, "sha256": duet.digest(data),
                               "mode": "100755" if relative.endswith(".sh") else "100644"}
        self.catalog = {"schema": 1, "profiles": {"orca": ["duet-manager"]}, "skills": {
            "duet-manager": {"name": "codex-duet", "source": "self", "path": "manager",
                "files": {"SKILL.md": duet.digest(b'---\nname: "codex-duet"\n---\n')}, "requires": []}}}
        duet.save(self.root / "catalog/skills.json", self.catalog)
        duet.save(self.root / "catalog/sources.lock.json", {"sources": {"mattpocock": {
            "path": "source", "url": "https://example.invalid/fixture", "revision": "1" * 40}}})
        duet.save(self.root / "catalog/bundles.lock.json", {"schema": 1, "bundles": {
            "mattpocock": {"name": "fixture", "source": "mattpocock", "revision": "1" * 40,
                          "files": files}}})
        (self.root / "manager").mkdir()
        (self.root / "adapters").mkdir()
        (self.root / "adapters/orca-bootstrap.py").write_text("print('{}')\n")
        lock_path = self.root / "catalog/bundles.lock.json"
        native_lock = duet.load(lock_path)
        native_lock["adapter_files"] = {"adapters/orca-bootstrap.py": duet.digest(b"print('{}')\n")}
        duet.save(lock_path, native_lock)
        (self.root / "manager/SKILL.md").write_bytes(b'---\nname: "codex-duet"\n---\n')
        for name in ("LICENSE", "NOTICE"):
            (self.root / name).write_text("fixture\n")
        # Git pin behavior has its own real-Git regression tests. These fixtures
        # isolate native packaging, ownership and overlay behavior.
        self.verify = patch.object(duet.Manager, "verify_source")
        self.verify.start()
        self.addCleanup(self.verify.stop)
        self.registry = patch.object(Integrations, "registry", return_value={})
        self.registry.start()
        self.addCleanup(self.registry.stop)
        self.integration = Integrations(self.root, self.home)

    def own(self, agent="codex"):
        i = self.integration
        output = i.rendered("mattpocock")
        target = self.home / agent / "fixture"
        target.mkdir(parents=True)
        for rel, data in output.items():
            p = target / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        records = i.records()
        records["agents"].setdefault(agent, {})["mattpocock"] = {
            "name": "fixture", "revision": "1" * 40, "install_path": str(target),
            "marketplace": str(i.marketplace), "external": None,
            "files": {p: duet.digest(b) for p, b in output.items()}}
        duet.save(i.receipt, records)
        return target

    def test_source_hash_drift_is_refused(self):
        (self.root / "source/skills/alpha/SKILL.md").write_text("unreviewed")
        with self.assertRaisesRegex(duet.DuetError, "drift"):
            self.integration.payload("mattpocock")

    def test_executable_resource_mode_is_preserved(self):
        self.integration.stage(["mattpocock"])
        tool = self.integration.plugin_root("mattpocock") / "skills/alpha/tool.sh"
        self.assertEqual(tool.stat().st_mode & 0o777, 0o755)

    def test_default_checkout_stays_free_of_runtime_installations(self):
        checkout = self.home / ".local/share/codex-duet"
        shutil.copytree(self.root, checkout)
        integration = Integrations(checkout, self.home)
        self.assertFalse(integration.share.is_relative_to(checkout))
        integration.stage(["mattpocock"])
        self.assertFalse((checkout / "native").exists())

    def test_extra_staged_file_is_not_copied_into_a_plugin(self):
        i = self.integration
        i.stage(["mattpocock"])
        (i.plugin_root("mattpocock") / "unexpected.js").write_text("unreviewed")
        with self.assertRaisesRegex(duet.DuetError, "staging changed"):
            i.stage(["mattpocock"])

    def test_two_agent_stale_capture_preserves_first_edit(self):
        codex, claude = self.own(), self.own("claude-code")
        relative = "skills/alpha/SKILL.md"
        (codex / relative).write_bytes((codex / relative).read_bytes() + b"Codex correction\n")
        self.integration.capture("mattpocock", relative, "codex")
        fresh = Integrations(self.root, self.home)
        self.assertIn(b"Codex correction", fresh.payload("mattpocock")[relative])
        (claude / relative).write_bytes((claude / relative).read_bytes() + b"Stale Claude correction\n")
        with self.assertRaisesRegex(duet.DuetError, "stale"):
            fresh.capture("mattpocock", relative, "claude-code")
        self.assertIn(b"Codex correction", fresh.payload("mattpocock")[relative])

    def test_overlay_upgrade_keeps_the_marketplace_address(self):
        old = self.integration.marketplace
        target = self.own()
        relative = "skills/alpha/SKILL.md"
        (target / relative).write_bytes((target / relative).read_bytes() + b"reviewed correction\n")
        self.integration.capture("mattpocock", relative, "codex")
        fresh = Integrations(self.root, self.home)
        self.assertNotEqual(fresh.identity, self.integration.identity)
        self.assertEqual(fresh.marketplace, old)

    def test_memory_rendering_does_not_depend_on_node_search_path(self):
        real = Integrations(duet.ROOT, self.home)
        with patch("integrations.shutil.which", return_value="/first/node"):
            first = real.rendered("claude-mem")
        with patch("integrations.shutil.which", return_value="/second/node"):
            second = real.rendered("claude-mem")
        for relative in (".mcp.json", "hooks/hooks.json", "hooks/codex-hooks.json"):
            self.assertEqual(first[relative], second[relative])

    def test_conflicting_memory_preferences_are_preserved(self):
        path = self.home / ".claude-mem/settings.json"
        duet.save(path, {"CLAUDE_MEM_FILE_READ_GATE_ENABLED": "true"})
        before = path.read_bytes()
        with self.assertRaisesRegex(duet.DuetError, "conflicts"):
            self.integration.memory_settings("claude")
        self.assertEqual(path.read_bytes(), before)

    def test_conflicting_memory_environment_is_rejected(self):
        with patch.dict(os.environ, {"CLAUDE_MEM_PROVIDER": "codex"}):
            with self.assertRaisesRegex(duet.DuetError, "Environment override"):
                self.integration.memory_settings("claude")

    def test_telemetry_opt_in_is_not_silently_reported_as_disabled(self):
        path = self.home / ".claude-mem/telemetry.json"
        duet.save(path, {"enabled": True})
        with self.assertRaisesRegex(duet.DuetError, "telemetry preference"):
            self.integration.memory_settings("claude")
        self.assertTrue(duet.load(path)["enabled"])

    def test_partial_runtime_write_does_not_block_a_retry(self):
        i = self.integration
        wrapper = b"#!/bin/sh\nexec node \"$@\"\n"
        (self.root / "adapters/node-run.sh").write_bytes(wrapper)
        i.lock["adapter_files"]["adapters/node-run.sh"] = duet.digest(wrapper)
        i.lock["bundles"]["claude-mem"] = {"files": {}}
        output = {"package.json": b"{}", "scripts/worker-service.cjs": b"// fixture"}
        original_write = Path.write_bytes

        def write(path, data):
            if path.name == "worker-service.cjs":
                raise OSError("simulated full disk")
            return original_write(path, data)

        with patch.object(i, "payload", return_value=output), patch("integrations.command"), \
                patch("integrations.shutil.which", side_effect=lambda name: "/fixture/" + name):
            with patch.object(Path, "write_bytes", write):
                with self.assertRaisesRegex(OSError, "full disk"):
                    i.prepare_memory("claude")
            self.assertFalse(i.runtime.exists())
            i.prepare_memory("claude")
        self.assertEqual((i.runtime / "scripts/worker-service.cjs").read_bytes(), output["scripts/worker-service.cjs"])

    def test_shutdown_accepts_closed_response_only_after_health_confirms_exit(self):
        with patch("integrations.urllib.request.urlopen", side_effect=[
                ConnectionResetError("worker exited before flushing"),
                urllib.error.URLError("connection refused")]) as request:
            self.integration.shutdown_memory("http://127.0.0.1:37701")
        self.assertEqual(request.call_count, 2)

    def test_captured_edit_can_be_reapplied_but_other_edits_are_protected(self):
        target = self.own()
        relative = "skills/alpha/SKILL.md"
        (target / relative).write_bytes((target / relative).read_bytes() + b"reviewed\n")
        self.integration.capture("mattpocock", relative, "codex")
        fresh = Integrations(self.root, self.home)
        self.assertEqual(fresh.plan(["mattpocock"], ["codex"])[0]["action"], "install")
        (target / "skills/alpha/tool.sh").write_text("unregistered edit")
        with self.assertRaisesRegex(duet.DuetError, "installed files changed"):
            fresh.plan(["mattpocock"], ["codex"])

    def test_remove_does_not_discard_native_cache_edits(self):
        target = self.own()
        (target / "mine.txt").write_text("preserve")
        with patch("integrations.command") as command:
            with self.assertRaisesRegex(duet.DuetError, "installed files changed"):
                self.integration.remove(["mattpocock"], ["codex"])
            command.assert_not_called()
        self.assertEqual((target / "mine.txt").read_text(), "preserve")

    def test_generated_manifest_cannot_be_captured_as_a_source_overlay(self):
        self.own()
        with self.assertRaisesRegex(duet.DuetError, "generated native"):
            self.integration.capture("mattpocock", ".codex-plugin/plugin.json", "codex")

    def test_unregistered_overlay_bytes_survive(self):
        target = self.own()
        relative = "skills/alpha/SKILL.md"
        self.integration.capture("mattpocock", relative, "codex")
        overlay = self.root / "overlays/native/mattpocock" / relative
        overlay.write_text("unregistered new work")
        with self.assertRaisesRegex(duet.DuetError, "drift|Unregistered"):
            Integrations(self.root, self.home).capture("mattpocock", relative, "codex")
        self.assertEqual(overlay.read_text(), "unregistered new work")


if __name__ == "__main__":
    unittest.main()
