from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import duet


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True,
                                   stderr=subprocess.PIPE).strip()


def init(path):
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "user.email", "fixture@example.invalid")


def commit(path, message):
    git(path, "add", ".")
    git(path, "commit", "-m", message)
    return git(path, "rev-parse", "HEAD")


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.origin = self.base / "origin"
        self.root = self.base / "manager"
        self.home = self.base / "home"
        self.home.mkdir()
        init(self.origin)
        (self.origin / "LICENSE").write_text("MIT fixture notice\n")
        for name in ("alpha", "beta"):
            folder = self.origin / "skills" / name
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text(
                f'---\nname: "{name}"\ndescription: "Fixture"\n---\n\nRead [details](DETAILS.md).\n')
            (folder / "DETAILS.md").write_text("Original details.\n")
            (folder / "excluded.txt").write_text("Do not install me.\n")
        self.initial = commit(self.origin, "initial")
        init(self.root)
        git(self.root, "-c", "protocol.file.allow=always", "submodule", "add",
            str(self.origin), "upstream/example")
        self.source = self.root / "upstream/example"
        self.sources = {"example": {
            "path": "upstream/example", "url": str(self.origin),
            "revision": self.initial, "license": "MIT",
            "license_files": {"LICENSE": duet.digest((self.source / "LICENSE").read_bytes())},
            "license_surface": duet.license_surface(self.source, self.initial)}}
        skills = {}
        for name in ("alpha", "beta"):
            folder = self.source / "skills" / name
            skills[name] = {
                "name": name, "source": "example", "path": "skills/" + name,
                "license": "MIT", "files": {f: duet.digest((folder / f).read_bytes())
                                             for f in ("SKILL.md", "DETAILS.md")},
                "requires": [], "overlays": {}}
        self.catalog = {"schema": 1, "profiles": {"basic": ["alpha"], "both": ["alpha", "beta"]},
                        "skills": skills}
        (self.root / "catalog").mkdir()
        duet.save(self.root / "catalog/sources.lock.json", {"schema": 1, "sources": self.sources})
        self.save_catalog()
        commit(self.root, "catalog")
        self.m = duet.Manager(self.root, self.home)

    def save_catalog(self):
        duet.save(self.root / "catalog/skills.json", self.catalog)

    def manager(self):
        return duet.Manager(self.root, self.home)

    def edit(self, key, relative, path):
        self.m.override(key, relative, path,
                        base_sha=self.m.file_info(key, relative)["effective_sha256"])

    def target(self, name="alpha", agent="codex"):
        return self.home / duet.AGENTS[agent] / name

    def upstream_commit(self, rel, content):
        path = self.origin / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        sha = commit(self.origin, "next")
        git(self.source, "fetch", "origin", sha)
        return sha

    def test_exact_filter_and_license_provenance(self):
        payload = self.m.payload("alpha")
        self.assertEqual(set(payload), {"SKILL.md", "DETAILS.md", ".duet/licenses/LICENSE", ".duet/origin.json"})
        self.assertEqual(json.loads(payload[".duet/origin.json"])["revision"], self.initial)

    def test_idempotent_install_and_independent_agents(self):
        self.assertEqual(self.m.install(["alpha"], "codex")[0]["action"], "install")
        before = self.m.receipt.read_bytes()
        self.assertEqual(self.m.install(["alpha"], "codex")[0]["action"], "unchanged")
        self.assertEqual(self.m.receipt.read_bytes(), before)
        self.assertFalse(self.target(agent="claude-code").exists())
        self.m.install(["alpha"], "claude-code")
        self.m.remove("codex", ["alpha"])
        self.assertTrue(self.target(agent="claude-code").exists())

    def test_selection_closes_dependencies_and_rejects_cycles(self):
        self.catalog["skills"]["alpha"]["requires"] = ["beta"]
        self.save_catalog()
        self.assertEqual(self.manager().selection("basic", []), ["beta", "alpha"])
        self.catalog["skills"]["beta"]["requires"] = ["alpha"]
        self.save_catalog()
        with self.assertRaisesRegex(duet.DuetError, "cycle"):
            self.manager().selection("basic", [])

    def test_unmanaged_target_is_never_adopted(self):
        target = self.target()
        target.mkdir(parents=True)
        (target / "personal.txt").write_text("mine")
        with self.assertRaisesRegex(duet.DuetError, "unmanaged"):
            self.m.install(["alpha"], "codex")
        self.assertEqual((target / "personal.txt").read_text(), "mine")

    def test_live_orca_plugin_collision(self):
        orca = {"skills": [{"name": "alpha", "providers": ["claude"], "sourceKind": "plugin"}]}
        with self.assertRaisesRegex(duet.DuetError, "plugin/bundle"):
            self.m.install(["alpha"], "claude-code", orca)
        self.assertFalse(self.target(agent="claude-code").exists())

    def test_legacy_codex_duplicate(self):
        (self.home / ".codex/skills/alpha").mkdir(parents=True)
        with self.assertRaisesRegex(duet.DuetError, "legacy"):
            self.m.plan(["alpha"], "codex")

    def test_symlink_escape_is_refused(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.home / ".agents").mkdir()
        (self.home / ".agents/skills").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(duet.DuetError, "Symlink"):
            self.m.install(["alpha"], "codex")
        self.assertEqual(list(outside.iterdir()), [])

    def test_dirty_source_is_refused(self):
        (self.source / "skills/alpha/SKILL.md").write_text("edited upstream")
        with self.assertRaisesRegex(duet.DuetError, "Dirty upstream"):
            self.m.payload("alpha")

    def test_gitlink_pin_mismatch_is_refused(self):
        self.m.sources["example"]["revision"] = "0" * 40
        with self.assertRaisesRegex(duet.DuetError, "Pin mismatch"):
            self.m.payload("alpha")

    def test_hash_tampering_is_refused(self):
        self.m.catalog["skills"]["alpha"]["files"]["DETAILS.md"] = "0" * 64
        with self.assertRaisesRegex(duet.DuetError, "File drift"):
            self.m.payload("alpha")

    def test_missing_resource_is_refused(self):
        del self.m.catalog["skills"]["alpha"]["files"]["DETAILS.md"]
        with self.assertRaisesRegex(duet.DuetError, "Missing filtered resource"):
            self.m.payload("alpha")

    def test_code_examples_are_not_resource_dependencies(self):
        file = self.base / "edited.md"
        file.write_text('---\nname: "alpha"\ndescription: "Fixture"\n---\n'
                        '```markdown\n[example](not-an-actual-resource.md)\n```\n'
                        '`[inline](also-not-real.md)`\n[details](DETAILS.md)\n')
        self.edit("alpha", "SKILL.md", file)
        self.assertEqual(self.m.payload("alpha")["SKILL.md"], file.read_bytes())

    def test_local_edit_requires_capture_and_survives_reapply(self):
        self.m.install(["alpha"], "codex")
        file = self.target() / "DETAILS.md"
        file.write_text("My correction.\n")
        with self.assertRaisesRegex(duet.DuetError, "Local edits"):
            self.m.install(["alpha"], "codex")
        with self.assertRaisesRegex(duet.DuetError, "Local edits"):
            self.m.remove("codex", ["alpha"])
        self.m.capture("alpha", "DETAILS.md", "codex")
        self.m.install(["alpha"], "codex")
        self.assertEqual(file.read_text(), "My correction.\n")
        self.assertEqual((self.source / "skills/alpha/DETAILS.md").read_text(), "Original details.\n")
        self.assertEqual(self.m.status("codex")[0]["state"], "clean")

    def test_install_write_failure_rolls_back_all_targets(self):
        self.m.install(["alpha"], "codex")
        original = duet.inventory(self.target())
        receipt = self.m.receipt.read_bytes()
        edited = self.base / "edit"
        edited.write_text("new details")
        self.edit("alpha", "DETAILS.md", edited)
        with patch("duet.save", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.m.install(["alpha", "beta"], "codex")
        self.assertEqual(duet.inventory(self.target()), original)
        self.assertFalse(self.target("beta").exists())
        self.assertEqual(self.m.receipt.read_bytes(), receipt)

    def test_remove_write_failure_restores_targets(self):
        self.m.install(["alpha", "beta"], "codex")
        receipt = self.m.receipt.read_bytes()
        with patch("duet.save", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.m.remove("codex", ["alpha", "beta"])
        self.assertTrue(self.target().exists())
        self.assertTrue(self.target("beta").exists())
        self.assertEqual(self.m.receipt.read_bytes(), receipt)

    def test_pin_updates_only_existing_filter_and_not_installed_files(self):
        self.m.install(["alpha"], "codex")
        sha = self.upstream_commit("skills/alpha/new-unreviewed.txt", "never deploy")
        self.m.pin("example", sha)
        self.assertNotIn("new-unreviewed.txt", self.m.payload("alpha"))
        self.assertFalse((self.target() / "new-unreviewed.txt").exists())
        self.assertEqual(self.m.status("codex")[0]["catalog"], "update-available")

    def test_license_change_is_rejected_before_checkout(self):
        sha = self.upstream_commit("LICENSE", "Different terms")
        with self.assertRaisesRegex(duet.DuetError, "License changed"):
            self.m.pin("example", sha)
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), self.initial)

    def test_new_nested_license_is_rejected(self):
        sha = self.upstream_commit("skills/alpha/LICENSE.txt", "New restriction")
        with self.assertRaisesRegex(duet.DuetError, "License files"):
            self.m.pin("example", sha)
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), self.initial)

    def test_overlay_conflict_restores_pin_and_catalog(self):
        edited = self.base / "edited"
        edited.write_text("my overlay")
        self.edit("alpha", "DETAILS.md", edited)
        catalog = self.m.catalog_path.read_bytes()
        sha = self.upstream_commit("skills/alpha/DETAILS.md", "changed base")
        with self.assertRaisesRegex(duet.DuetError, "Overlay base changed"):
            self.m.pin("example", sha)
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), self.initial)
        self.assertEqual(self.m.catalog_path.read_bytes(), catalog)
        self.m.verify_source("example")

    def test_two_agent_stale_capture_preserves_first_overlay(self):
        self.m.install(["alpha"], "codex")
        self.m.install(["alpha"], "claude-code")
        codex = self.target() / "DETAILS.md"
        codex.write_text("Codex correction")
        self.m.capture("alpha", "DETAILS.md", "codex")
        self.m.install(["alpha"], "codex")
        other = self.target(agent="claude-code") / "DETAILS.md"
        other.write_text("Claude correction from older base")
        with self.assertRaisesRegex(duet.DuetError, "stale"):
            self.m.capture("alpha", "DETAILS.md", "claude-code")
        self.assertEqual(self.m.payload("alpha")["DETAILS.md"], b"Codex correction")
        self.assertEqual(other.read_text(), "Claude correction from older base")

    def test_capture_from_old_pin_cannot_replace_upstream_fix(self):
        self.m.install(["alpha"], "codex")
        sha = self.upstream_commit("skills/alpha/DETAILS.md", "New upstream fix")
        self.m.pin("example", sha)
        (self.target() / "DETAILS.md").write_text("Local edit from old upstream")
        with self.assertRaisesRegex(duet.DuetError, "stale"):
            self.m.capture("alpha", "DETAILS.md", "codex")
        self.assertEqual(self.m.payload("alpha")["DETAILS.md"], b"New upstream fix")

    def test_explicit_rebased_overlay_can_advance_pin(self):
        edited = self.base / "edited"
        edited.write_text("Original details plus local correction")
        self.edit("alpha", "DETAILS.md", edited)
        sha = self.upstream_commit("skills/alpha/DETAILS.md", "Upstream v2")
        edited.write_text("Upstream v2 plus local correction")
        self.m.pin("example", sha, [("alpha", "DETAILS.md", str(edited))])
        self.assertEqual(self.m.payload("alpha")["DETAILS.md"], edited.read_bytes())
        self.m.verify_source("example")

    def test_removed_catalog_component_can_be_uninstalled_by_receipt(self):
        self.m.install(["beta"], "codex")
        del self.catalog["skills"]["beta"]
        self.save_catalog()
        m = self.manager()
        selected = m.selection(None, ["beta"], dependencies=False, additional=["beta"])
        self.assertEqual(m.remove("codex", selected), ["beta"])
        self.assertFalse(self.target("beta").exists())

    def test_removal_preserves_shared_dependency(self):
        self.catalog["skills"]["alpha"]["requires"] = ["beta"]
        self.save_catalog()
        m = self.manager()
        m.install(m.selection(None, ["alpha"]), "codex")
        with self.assertRaisesRegex(duet.DuetError, "requires"):
            m.remove("codex", ["beta"])
        m.remove("codex", m.selection(None, ["alpha"], dependencies=False))
        self.assertFalse(self.target().exists())
        self.assertTrue(self.target("beta").exists())

    def test_different_checkout_requires_explicit_adoption(self):
        self.m.install(["alpha"], "codex")
        records = self.m.records()
        records["checkout"] = "/some/other/checkout"
        duet.save(self.m.receipt, records)
        with self.assertRaisesRegex(duet.DuetError, "adopt-checkout"):
            self.m.install(["alpha"], "codex")
        self.m.install(["alpha"], "codex", adopt=True)
        self.assertEqual(self.m.records()["checkout"], str(self.root.resolve()))

    def test_edit_during_staging_is_detected_and_restored(self):
        self.m.install(["alpha"], "codex")
        edited = self.base / "edit"
        edited.write_text("Reviewed update")
        self.edit("alpha", "DETAILS.md", edited)
        original_payload = self.m.payload
        calls = 0

        def payload(key):
            nonlocal calls
            calls += 1
            result = original_payload(key)
            if calls == 2:
                (self.target() / "DETAILS.md").write_text("New edit while installing")
            return result

        with patch.object(self.m, "payload", payload):
            with self.assertRaisesRegex(duet.DuetError, "during staging"):
                self.m.install(["alpha"], "codex")
        self.assertEqual((self.target() / "DETAILS.md").read_text(), "New edit while installing")

    def test_lost_receipt_recovery_requires_exact_content(self):
        self.m.install(["alpha"], "codex")
        self.m.receipt.unlink()
        with self.assertRaisesRegex(duet.DuetError, "unmanaged"):
            self.m.install(["alpha"], "codex")
        self.m.install(["alpha"], "codex", recover=True)
        self.assertEqual(self.m.status("codex")[0]["state"], "clean")
        self.m.receipt.unlink()
        (self.target() / "DETAILS.md").write_text("must preserve this")
        with self.assertRaisesRegex(duet.DuetError, "unmanaged"):
            self.m.install(["alpha"], "codex", recover=True)
        self.assertEqual((self.target() / "DETAILS.md").read_text(), "must preserve this")

    def test_catalog_rename_cannot_leave_duplicate_component(self):
        self.m.install(["alpha"], "codex")
        self.m.catalog["skills"]["alpha"]["name"] = "alpha-renamed"
        duet.save(self.m.catalog_path, self.m.catalog)
        edited = self.base / "renamed"
        edited.write_text((self.source / "skills/alpha/SKILL.md").read_text().replace('"alpha"', '"alpha-renamed"'))
        self.edit("alpha", "SKILL.md", edited)
        with self.assertRaisesRegex(duet.DuetError, "before renaming"):
            self.m.install(["alpha"], "codex")
        self.assertFalse(self.target("alpha-renamed").exists())
        self.assertTrue(self.target().exists())

    def test_bad_rebase_restores_original_overlay_bytes(self):
        edited = self.base / "edited"
        edited.write_text("my details")
        self.edit("alpha", "DETAILS.md", edited)
        before = (self.root / "overlays/alpha/DETAILS.md").read_bytes()
        sha = self.upstream_commit("skills/alpha/SKILL.md", '---\nname: "wrong-name"\n---\n')
        edited.write_text("rebased but another validation will fail")
        with self.assertRaisesRegex(duet.DuetError, "name mismatch"):
            self.m.pin("example", sha, [("alpha", "DETAILS.md", str(edited))])
        self.assertEqual((self.root / "overlays/alpha/DETAILS.md").read_bytes(), before)
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), self.initial)

    def test_unregistered_overlay_edits_are_not_discarded(self):
        edited = self.base / "edited"
        edited.write_text("reviewed overlay")
        self.edit("alpha", "DETAILS.md", edited)
        target = self.root / "overlays/alpha/DETAILS.md"
        target.write_text("new unregistered correction")
        with self.assertRaisesRegex(duet.DuetError, "Unregistered overlay"):
            self.edit("alpha", "DETAILS.md", edited)
        self.assertEqual(target.read_text(), "new unregistered correction")
        self.edit("alpha", "DETAILS.md", target)
        self.assertEqual(self.m.payload("alpha")["DETAILS.md"], b"new unregistered correction")

    def test_failed_rollback_retains_original_bytes(self):
        self.m.install(["alpha"], "codex")
        edited = self.base / "edited"
        edited.write_text("reviewed update")
        self.edit("alpha", "DETAILS.md", edited)
        original_rename = Path.rename

        def rename(path, target):
            if path.name == "old":
                raise OSError("restoration blocked")
            return original_rename(path, target)

        with patch("duet.save", side_effect=OSError("disk error")), patch.object(Path, "rename", rename):
            with self.assertRaisesRegex(duet.DuetError, "backups retained"):
                self.m.install(["alpha"], "codex")
        backups = list(self.target().parent.glob(".duet-*/old/DETAILS.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "Original details.\n")

    def test_override_cannot_bypass_stale_managed_installation(self):
        self.m.install(["alpha"], "codex")
        self.m.install(["alpha"], "claude-code")
        (self.target() / "DETAILS.md").write_text("Codex correction")
        self.m.capture("alpha", "DETAILS.md", "codex")
        self.m.install(["alpha"], "codex")
        other = self.target(agent="claude-code") / "DETAILS.md"
        other.write_text("Stale Claude correction")
        current = self.m.file_info("alpha", "DETAILS.md")["effective_sha256"]
        with self.assertRaisesRegex(duet.DuetError, "use capture"):
            self.m.override("alpha", "DETAILS.md", other, base_sha=current)
        self.assertEqual(self.m.payload("alpha")["DETAILS.md"], b"Codex correction")

    def test_retired_sync_has_actionable_removal_and_no_partial_apply(self):
        self.m.install(["alpha", "beta"], "codex")
        del self.catalog["skills"]["beta"]
        self.save_catalog()
        m = self.manager()
        before = duet.inventory(self.target())
        with self.assertRaisesRegex(duet.DuetError, "remove --skill beta --agent codex"):
            m.sync({"skills": []})
        self.assertEqual(duet.inventory(self.target()), before)
        self.assertTrue(self.target("beta").exists())


if __name__ == "__main__":
    unittest.main()
