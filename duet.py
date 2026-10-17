#!/usr/bin/env python3
"""Pinned, selective skill management for Orca. Standard library only."""
from __future__ import annotations

import argparse
import contextlib
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent
AGENTS = {"codex": ".agents/skills", "claude-code": ".claude/skills"}


class DuetError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(*args: str, cwd: Path | None = None) -> str:
    p = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=90)
    if p.returncode:
        raise DuetError(f"Command failed: {shlex.join(args)}\n{p.stderr.strip()}")
    return p.stdout.strip()


def safe(base: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if not relative or rel.is_absolute() or any(p in ("..", "") for p in rel.parts):
        raise DuetError(f"Unsafe relative path: {relative}")
    current = base
    if current.is_symlink():
        raise DuetError(f"Symlink is not allowed: {current}")
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise DuetError(f"Symlink is not allowed: {current}")
    return current


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise DuetError(f"Cannot read {path}: {exc}") from exc


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def inventory(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_dir():
        raise DuetError(f"Expected an ordinary directory: {path}")
    result = {}
    for p in path.rglob("*"):
        if p.is_symlink():
            raise DuetError(f"Unexpected symlink: {p}")
        if p.is_file():
            result[p.relative_to(path).as_posix()] = digest(p.read_bytes())
    return result


def license_surface(path: Path, revision: str) -> dict[str, str]:
    paths = run("git", "ls-tree", "-r", "--name-only", revision, cwd=path).splitlines()
    result = {}
    for rel in paths:
        if re.search(r"(?:^|/)(?:LICENSE[^/]*|NOTICE[^/]*|COPYING[^/]*)$", rel, re.I):
            blob = subprocess.check_output(["git", "show", revision + ":" + rel], cwd=path)
            result[rel] = digest(blob)
    return result


def staged_directory(stack, parent: Path, retained: set[Path]) -> Path:
    path = Path(tempfile.mkdtemp(prefix=".duet-", dir=parent))
    def cleanup():
        if path not in retained:
            shutil.rmtree(path)
    stack.callback(cleanup)
    return path


def orca_command() -> list[str]:
    if os.environ.get("ORCA_CLI_COMMAND"):
        return shlex.split(os.environ["ORCA_CLI_COMMAND"])
    if os.environ.get("ORCA_DEV_REPO_ROOT"):
        return ["orca-dev"]
    if sys.platform.startswith("linux") and not os.environ.get("ORCA_TERMINAL_HANDLE"):
        return ["orca-ide"]
    return ["orca"]


def orca_check() -> dict:
    command = orca_command()
    if not command or not shutil.which(command[0]):
        raise DuetError("Orca CLI is unavailable. Run from the Orca execution host.")
    status = json.loads(run(*command, "status", "--json"))
    result = status.get("result", {})
    if not status.get("ok") or result.get("runtime", {}).get("state") != "ready":
        raise DuetError("Orca runtime is not ready. No installation was performed.")
    installed = json.loads(run(*command, "skills", "installed", "--json"))
    if not installed.get("ok"):
        raise DuetError("Could not verify Orca skill inventory.")
    return {"version": result.get("runtime", {}).get("appVersion"),
            "skills": installed.get("result", {}).get("skills", [])}


class Manager:
    def __init__(self, root: Path = ROOT, home: Path | None = None):
        self.root = root.resolve()
        self.home = (home or Path.home()).expanduser().resolve()
        self.catalog_path = self.root / "catalog/skills.json"
        self.lock_path = self.root / "catalog/sources.lock.json"
        self.catalog = load(self.catalog_path)
        self.sources = load(self.lock_path)["sources"]
        self.state = safe(self.home, ".local/state/codex-duet")
        self.receipt = self.state / "installations.json"

    @contextlib.contextmanager
    def locked(self):
        self.state.mkdir(parents=True, exist_ok=True)
        lock = safe(self.state, "manager.lock")
        with lock.open("a+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            self.catalog = load(self.catalog_path)
            self.sources = load(self.lock_path)["sources"]
            yield

    def records(self) -> dict:
        safe(self.state, "installations.json")
        return load(self.receipt) if self.receipt.exists() else {"schema": 1, "agents": {}}

    def selection(self, profile: str | None, selected: list[str], *, dependencies=True,
                  additional=()) -> list[str]:
        picks = list(selected)
        if profile:
            if profile not in self.catalog["profiles"]:
                raise DuetError(f"Unknown profile: {profile}")
            picks += self.catalog["profiles"][profile]
        if not picks:
            raise DuetError("Choose --profile or --skill. Nothing is selected implicitly.")
        if not dependencies:
            for name in picks:
                if name not in self.catalog["skills"] and name not in additional:
                    raise DuetError(f"Unknown skill: {name}")
            return list(dict.fromkeys(picks))
        ordered, active, done = [], set(), set()

        def visit(name):
            if name not in self.catalog["skills"]:
                raise DuetError(f"Unknown skill: {name}")
            if name in active:
                raise DuetError(f"Dependency cycle at {name}")
            if name in done:
                return
            active.add(name)
            for dep in self.catalog["skills"][name].get("requires", []):
                visit(dep)
            active.remove(name)
            done.add(name)
            ordered.append(name)

        for name in picks:
            visit(name)
        return ordered

    def verify_source(self, name: str) -> None:
        source = self.sources[name]
        path = safe(self.root, source["path"])
        if not re.fullmatch(r"[0-9a-f]{40}", source["revision"]):
            raise DuetError(f"Full commit SHA required: {name}")
        head = run("git", "rev-parse", "HEAD", cwd=path)
        if head != source["revision"]:
            raise DuetError(f"Pin mismatch: {name}; expected {source['revision']}, got {head}")
        entry = run("git", "ls-files", "--stage", "--", source["path"], cwd=self.root)
        if not entry.startswith("160000 " + head + " 0\t"):
            raise DuetError(f"Gitlink does not match lock: {name}")
        url = run("git", "config", "-f", ".gitmodules", "--get",
                  f"submodule.{source['path']}.url", cwd=self.root)
        if url != source["url"]:
            raise DuetError(f"Submodule URL mismatch: {name}")
        if run("git", "status", "--porcelain", "--untracked-files=all", cwd=path):
            raise DuetError(f"Dirty upstream: {name}. Keep changes in overlays instead.")
        for rel, expected in source.get("license_files", {}).items():
            if digest(safe(path, rel).read_bytes()) != expected:
                raise DuetError(f"License drift: {name}/{rel}")
        if source.get("license_surface") != license_surface(path, head):
            raise DuetError(f"License inventory mismatch: {name}")

    def payload(self, key: str) -> dict[str, bytes]:
        skill = self.catalog["skills"][key]
        name = skill["name"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
            raise DuetError(f"Invalid installed skill name: {name}")
        source_id = skill["source"]
        if source_id == "self":
            base = self.root
        else:
            self.verify_source(source_id)
            base = safe(self.root, self.sources[source_id]["path"])
        folder = safe(base, skill["path"])
        if "SKILL.md" not in skill["files"]:
            raise DuetError(f"No SKILL.md in allowlist: {key}")
        output = {}
        for rel, expected in skill["files"].items():
            raw = safe(folder, rel).read_bytes()
            if digest(raw) != expected:
                raise DuetError(f"File drift: {key}/{rel}. Review the pin/catalog first.")
            override = skill.get("overlays", {}).get(rel)
            if override:
                if override["base_sha256"] != expected:
                    raise DuetError(f"Overlay base changed: {key}/{rel}")
                raw = safe(self.root, override["path"]).read_bytes()
                if digest(raw) != override["sha256"]:
                    raise DuetError(f"Overlay drift: {key}/{rel}; import it again with override.")
            output[rel] = raw
        for rel in skill.get("overlays", {}):
            if rel not in skill["files"]:
                raise DuetError(f"Overlay is not allowlisted: {key}/{rel}")
        front = output["SKILL.md"].decode()
        match = re.search(r'^name:\s*[\'\"]?([a-z0-9-]+)[\'\"]?\s*$', front, re.M)
        if not match or match.group(1) != name:
            raise DuetError(f"SKILL.md name mismatch: {key}")
        # Reject missing local Markdown resources; no wildcard expansion on updates.
        for rel, raw in list(output.items()):
            if not rel.endswith(".md"):
                continue
            text = re.sub(r"(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[^\n]*$", "", raw.decode())
            text = re.sub(r"`[^`\n]+`", "", text)
            for ref in re.findall(r'\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)', text):
                if ref.startswith(("https:", "http:", "mailto:", "#")):
                    continue
                ref = unquote(ref.split("#")[0])
                target = os.path.normpath(str(PurePosixPath(rel).parent / ref)).replace(os.sep, "/")
                if target not in output:
                    raise DuetError(f"Missing filtered resource: {key}/{rel} -> {ref}")
        if source_id == "self":
            for rel in ("LICENSE", "NOTICE"):
                output[".duet/licenses/" + rel] = safe(self.root, rel).read_bytes()
        else:
            source = self.sources[source_id]
            for rel in source["license_files"]:
                output[".duet/licenses/" + rel] = safe(base, rel).read_bytes()
            output[".duet/origin.json"] = (json.dumps({
                "source": source["url"], "revision": source["revision"],
                "path": skill["path"], "license": skill["license"],
                "modified_files": sorted(skill.get("overlays", {})),
            }, indent=2) + "\n").encode()
        return output

    def plan(self, selected: list[str], agent: str, orca: dict | None = None,
             adopt=False, recover=False) -> list[dict]:
        state = self.records()
        if state.get("checkout") not in (None, str(self.root)) and not adopt:
            raise DuetError("Different managing checkout: " + state["checkout"]
                            + ". Review possible downgrades, then use --adopt-checkout explicitly.")
        records = state.get("agents", {}).get(agent, {})
        result, names = [], set()
        for key in selected:
            skill = self.catalog["skills"][key]
            name = skill["name"]
            if any(r["component"] == key and previous != name for previous, r in records.items()):
                raise DuetError(f"Component {key} was installed under another name; remove it before renaming.")
            if name in names:
                raise DuetError(f"Two selected skills have the same name: {name}")
            names.add(name)
            data = self.payload(key)
            expected = {p: digest(b) for p, b in data.items()}
            target = safe(self.home, AGENTS[agent] + "/" + name)
            owned = records.get(name)
            if owned and owned["component"] != key:
                raise DuetError(f"Installed name belongs to another component: {name}")
            action = "install"
            current = None
            if target.exists():
                current = inventory(target)
                if not owned:
                    if not recover or current != expected:
                        raise DuetError(f"Existing unmanaged skill; refusing to overwrite: {target}. Exact reviewed content can be recovered with --recover.")
                    owned = {"files": expected, "requires": skill.get("requires", []), "checkout": None}
                reviewed_edits = (set(current) == set(owned["files"])
                                  and all(value in (owned["files"].get(path), expected.get(path))
                                          for path, value in current.items()))
                if not reviewed_edits and current != expected:
                    extra = sorted(set(current) - set(owned["files"]))
                    detail = (f" Non-catalog files: {extra}; preserve/move them outside first."
                              if extra else " Capture changed allowlisted files first.")
                    raise DuetError(f"Local edits: {name}." + detail)
                action = ("unchanged" if current == expected and owned["files"] == expected
                          and owned.get("requires", []) == skill.get("requires", [])
                          and owned.get("checkout") == str(self.root) else "update")
            elif owned:
                action = "restore-missing"
            # Codex also discovers legacy user skills; do not hide duplicate names there.
            if agent == "codex" and safe(self.home, ".codex/skills/" + name).exists():
                raise DuetError(f"Duplicate legacy Codex skill: {name}")
            if orca:
                provider = "codex" if agent == "codex" else "claude"
                duplicates = [s for s in orca["skills"] if s["name"] == name
                              and provider in s.get("providers", [])
                              and s.get("sourceKind") in ("plugin", "bundled")]
                if duplicates:
                    raise DuetError(f"Orca already provides {name} through a plugin/bundle.")
            result.append({"component": key, "name": name, "agent": agent,
                           "target": str(target), "action": action, "files": expected,
                           "before_files": current,
                           "current_checkout": state.get("checkout"),
                           "desired_checkout": str(self.root)})
        return result

    def install(self, selected: list[str], agent: str, orca: dict | None = None,
                adopt=False, recover=False) -> list[dict]:
        with self.locked():
            plan = self.plan(selected, agent, orca, adopt, recover)
            records = self.records()
            checkout_changed = records.get("checkout") != str(self.root)
            records["checkout"] = str(self.root)
            owned = records["agents"].setdefault(agent, {})
            rollback = []
            retained = set()
            with contextlib.ExitStack() as stack:
                try:
                    for entry in plan:
                        if entry["action"] == "unchanged":
                            continue
                        target = Path(entry["target"])
                        target.parent.mkdir(parents=True, exist_ok=True)
                        staging = staged_directory(stack, target.parent, retained)
                        candidate = staging / "new"
                        candidate.mkdir()
                        for rel, data in self.payload(entry["component"]).items():
                            p = safe(candidate, rel)
                            p.parent.mkdir(parents=True, exist_ok=True)
                            p.write_bytes(data)
                        backup = staging / "old"
                        existed = target.exists()
                        if existed != (entry["before_files"] is not None):
                            raise DuetError(f"Installation target changed during staging: {target}")
                        if existed:
                            target.rename(backup)
                        rollback.append((target, backup, existed, entry["files"], False))
                        if existed and inventory(backup) != entry["before_files"]:
                            raise DuetError(f"Local edits appeared during staging: {target}")
                        candidate.rename(target)
                        rollback[-1] = (target, backup, existed, entry["files"], True)
                        owned[entry["name"]] = {"component": entry["component"], "files": entry["files"],
                                                "requires": self.catalog["skills"][entry["component"]].get("requires", []),
                                                "checkout": str(self.root)}
                    if rollback or checkout_changed:
                        save(self.receipt, records)
                except BaseException as error:
                    failures = []
                    for target, backup, existed, expected, installed in reversed(rollback):
                        try:
                            if target.exists() or target.is_symlink():
                                if not installed or inventory(target) != expected:
                                    raise DuetError("Target changed during rollback")
                                shutil.rmtree(target)
                            if existed:
                                backup.rename(target)
                        except BaseException:
                            retained.add(backup.parent)
                            failures.append(str(backup.parent))
                    if failures:
                        raise DuetError("Rollback incomplete; backups retained at: " + ", ".join(failures)) from error
                    raise
            return plan

    def status(self, agent: str) -> list[dict]:
        rows = []
        for name, record in self.records().get("agents", {}).get(agent, {}).items():
            target = safe(self.home, AGENTS[agent] + "/" + name)
            actual = inventory(target) if target.exists() else None
            state = "missing" if actual is None else ("clean" if actual == record["files"] else "modified")
            row = {"name": name, "component": record["component"], "state": state}
            try:
                desired = {p: digest(b) for p, b in self.payload(record["component"]).items()}
                row["catalog"] = "current" if desired == record["files"] else "update-available"
            except (DuetError, OSError, KeyError) as exc:
                row["catalog"] = "unverifiable"
                row["reason"] = str(exc)
            rows.append(row)
        return rows

    def remove(self, agent: str, selected: list[str]) -> list[str]:
        with self.locked():
            records = self.records()
            owned = records["agents"].get(agent, {})
            graph = {r["component"]: r.get("requires", self.catalog["skills"].get(
                r["component"], {}).get("requires", [])) for r in owned.values()}
            removed = set(selected)
            for component in set(graph) - removed:
                pending, seen = list(graph[component]), set()
                while pending:
                    dep = pending.pop()
                    if dep in seen:
                        continue
                    seen.add(dep)
                    if dep in removed:
                        raise DuetError(f"Cannot remove {dep}; retained component {component} requires it.")
                    pending.extend(graph.get(dep, []))
            targets = []
            for name, record in owned.items():
                if record["component"] not in selected:
                    continue
                path = safe(self.home, AGENTS[agent] + "/" + name)
                if path.exists() and inventory(path) != record["files"]:
                    extra = sorted(set(inventory(path)) - set(record["files"]))
                    raise DuetError(f"Local edits: {name}. Capture allowlisted changes; preserve/move non-catalog files outside: {extra}")
                targets.append((name, path))
            with contextlib.ExitStack() as stack:
                backups = []
                retained = set()
                try:
                    for name, path in targets:
                        if path.exists():
                            parent = staged_directory(stack, path.parent, retained)
                            backup = parent / "removed"
                            path.rename(backup)
                            backups.append((path, backup))
                            if inventory(backup) != owned[name]["files"]:
                                raise DuetError(f"Local edits appeared while removing {name}")
                        del owned[name]
                    if targets:
                        save(self.receipt, records)
                except BaseException as error:
                    failures = []
                    for path, backup in reversed(backups):
                        try:
                            if path.exists() or path.is_symlink():
                                raise DuetError("Target reappeared during rollback")
                            backup.rename(path)
                        except BaseException:
                            retained.add(backup.parent)
                            failures.append(str(backup.parent))
                    if failures:
                        raise DuetError("Rollback incomplete; backups retained at: " + ", ".join(failures)) from error
                    raise
            return [name for name, _ in targets]

    def file_info(self, key: str, relative: str) -> dict:
        skill = self.catalog["skills"].get(key)
        if not skill or relative not in skill["files"]:
            raise DuetError("Only already-allowlisted files can be edited.")
        return {"component": key, "file": relative, "upstream_sha256": skill["files"][relative],
                "effective_sha256": skill.get("overlays", {}).get(relative, {}).get("sha256", skill["files"][relative])}

    def capture(self, key: str, relative: str, agent: str) -> None:
        name = self.catalog["skills"][key]["name"]
        record = self.records().get("agents", {}).get(agent, {}).get(name)
        if not record or record["component"] != key or relative not in record["files"]:
            raise DuetError("capture requires an owned, allowlisted installed file")
        edited = safe(self.home, AGENTS[agent] + "/" + name + "/" + relative)
        self.override(key, relative, edited, base_sha=record["files"][relative], from_capture=True)

    def override(self, key: str, relative: str, edited: Path, *, base_sha=None,
                 from_capture=False) -> None:
        skill = self.catalog["skills"].get(key)
        if not skill or relative not in skill["files"]:
            raise DuetError("Only already-allowlisted files can be overridden.")
        if not from_capture:
            for agent, records in self.records()["agents"].items():
                for name in records:
                    installed = safe(self.home, AGENTS[agent] + "/" + name)
                    if edited.resolve().is_relative_to(installed.resolve()):
                        raise DuetError("Managed installed file: use capture so its recorded edit base cannot be bypassed.")
        expected = self.file_info(key, relative)["effective_sha256"]
        if base_sha != expected:
            raise DuetError("Edit base is missing or stale; inspect file-info and rebase against the current payload before overriding.")
        data = edited.read_bytes()
        rel = f"overlays/{key}/{relative}"
        target = safe(self.root, rel)
        old_catalog = copy.deepcopy(self.catalog)
        old_data = target.read_bytes() if target.exists() else None
        existing = skill.get("overlays", {}).get(relative)
        if (existing and old_data is not None and digest(old_data) != existing["sha256"]
                and edited.resolve() != target.resolve()):
            raise DuetError("Unregistered overlay edits exist. Preserve them or import that overlay file itself first.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        skill.setdefault("overlays", {})[relative] = {
            "path": rel, "base_sha256": skill["files"][relative], "sha256": digest(data)}
        try:
            self.payload(key)
            save(self.catalog_path, self.catalog)
        except BaseException:
            self.catalog = old_catalog
            if old_data is None:
                target.unlink()
            else:
                target.write_bytes(old_data)
            raise

    def pin(self, source_id: str, revision: str, rebases=None) -> dict:
        if source_id not in self.sources or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise DuetError("Choose a known source and full 40-character commit SHA.")
        self.verify_source(source_id)
        for key, component in self.catalog["skills"].items():
            if component["source"] == source_id:
                self.payload(key)
        source = self.sources[source_id]
        path = safe(self.root, source["path"])
        old = source["revision"]
        # No network request and no branch-following operation here.
        run("git", "cat-file", "-e", revision + "^{commit}", cwd=path)
        for rel, expected in source["license_files"].items():
            blob = subprocess.check_output(["git", "show", revision + ":" + rel], cwd=path)
            if digest(blob) != expected:
                raise DuetError(f"License changed at {rel}; separate license review required.")
        if license_surface(path, revision) != source.get("license_surface"):
            raise DuetError("License files were added/removed/changed; separate license review required.")
        before_catalog, before_lock = self.catalog_path.read_bytes(), self.lock_path.read_bytes()
        rebases = rebases or []
        pending, old_overlays = {}, {}
        for key, relative, edited in rebases:
            skill = self.catalog["skills"].get(key, {})
            if skill.get("source") != source_id or relative not in skill.get("overlays", {}):
                raise DuetError("--rebase-file must name an existing overlay in this source")
            pending[key, relative] = Path(edited).read_bytes()
        report = run("git", "diff", "--stat", old, revision, cwd=path)
        try:
            run("git", "checkout", "--detach", revision, cwd=path)
            run("git", "add", "--", source["path"], cwd=self.root)
            source["revision"] = revision
            save(self.lock_path, {"schema": 1, "sources": self.sources})
            for key, skill in self.catalog["skills"].items():
                if skill["source"] != source_id:
                    continue
                folder = safe(path, skill["path"])
                for rel in skill["files"]:
                    skill["files"][rel] = digest(safe(folder, rel).read_bytes())
            for (key, relative), data in pending.items():
                skill = self.catalog["skills"][key]
                overlay = skill["overlays"][relative]
                target = safe(self.root, overlay["path"])
                old_overlays[target] = target.read_bytes()
                target.write_bytes(data)
                overlay.update(base_sha256=skill["files"][relative], sha256=digest(data))
            for key, skill in self.catalog["skills"].items():
                if skill["source"] != source_id:
                    continue
                self.payload(key)
            save(self.catalog_path, self.catalog)
        except BaseException:
            for target, data in old_overlays.items():
                target.write_bytes(data)
            self.catalog_path.write_bytes(before_catalog)
            self.lock_path.write_bytes(before_lock)
            self.catalog = json.loads(before_catalog)
            self.sources = json.loads(before_lock)["sources"]
            run("git", "checkout", "--detach", old, cwd=path)
            run("git", "add", "--", source["path"], cwd=self.root)
            raise
        return {"source": source_id, "before": old, "after": revision,
                "diff_stat": report, "installed_skills_changed": False,
                "note": "Gitlink staged. Review and commit lock/catalog/gitlink together."}

    def sync(self, live: dict, adopt=False) -> dict:
        selections = {}
        for agent, records in self.records()["agents"].items():
            retired = sorted({r["component"] for r in records.values()
                              if r["component"] not in self.catalog["skills"]})
            if retired:
                commands = [f"remove --skill {key} --agent {agent}" for key in retired]
                raise DuetError("Retired installed components were preserved. Restore their catalog entries or explicitly run: "
                                + "; ".join(commands) + ". Then retry sync; no skill was changed.")
            if records:
                selections[agent] = self.selection(None, [r["component"] for r in records.values()])
        for agent, selected in selections.items():
            self.plan(selected, agent, live, adopt)
        return {agent: self.install(selected, agent, live, adopt)
                for agent, selected in selections.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "verify", "plan", "install", "sync", "status", "doctor", "remove", "file-info", "override", "capture", "pin"])
    parser.add_argument("--profile")
    parser.add_argument("--skill", action="append", default=[])
    parser.add_argument("--agent", choices=AGENTS, default="codex")
    parser.add_argument("--home", type=Path, help="Alternate home for rehearsal; never changes agent configuration elsewhere")
    parser.add_argument("--file")
    parser.add_argument("--from", dest="edited", type=Path)
    parser.add_argument("--source")
    parser.add_argument("--rev")
    parser.add_argument("--base-sha")
    parser.add_argument("--rebase-file", nargs=3, action="append", default=[], metavar=("SKILL", "RELATIVE", "EDITED"))
    parser.add_argument("--adopt-checkout", action="store_true")
    parser.add_argument("--recover", action="store_true", help="Adopt only an exact copy of the reviewed payload after lost receipts")
    args = parser.parse_args()
    try:
        manager = Manager(home=args.home)
        if args.command == "list":
            output = {"profiles": manager.catalog["profiles"], "skills": {
                key: {k: v for k, v in value.items() if k in ("name", "source", "license", "requires")}
                for key, value in manager.catalog["skills"].items()}, "sources": manager.sources}
        elif args.command == "sync":
            output = manager.sync(orca_check(), args.adopt_checkout)
        elif args.command in ("status", "doctor"):
            output = {"installed": manager.status(args.agent)}
            if args.command == "doctor":
                output["orca"] = orca_check()["version"]
                for name in manager.sources:
                    manager.verify_source(name)
                output["pins"] = "verified"
        elif args.command == "pin":
            if not args.source or not args.rev:
                raise DuetError("pin requires --source and --rev")
            with manager.locked():
                output = manager.pin(args.source, args.rev, args.rebase_file)
        else:
            independent = args.command in ("override", "capture", "file-info", "remove")
            known = [r["component"] for r in manager.records().get("agents", {}).get(args.agent, {}).values()]
            selected = manager.selection(args.profile, args.skill, dependencies=not independent,
                                         additional=known if args.command == "remove" else ())
            if args.command == "verify":
                output = {"verified": selected}
                for key in selected:
                    manager.payload(key)
            elif args.command == "plan":
                output = manager.plan(selected, args.agent, adopt=args.adopt_checkout, recover=args.recover)
            elif args.command == "install":
                output = manager.install(selected, args.agent, orca_check(), args.adopt_checkout, args.recover)
            elif args.command == "remove":
                output = manager.remove(args.agent, selected)
            elif args.command in ("override", "capture", "file-info"):
                if len(selected) != 1 or not args.file:
                    raise DuetError("Choose exactly one --skill and --file")
                key = selected[0]
                if args.command == "file-info":
                    output = manager.file_info(key, args.file)
                    print(json.dumps(output, ensure_ascii=False, indent=2))
                    return 0
                if args.command == "override" and not args.edited:
                    raise DuetError("override requires --from FILE")
                with manager.locked():
                    if args.command == "capture":
                        manager.capture(key, args.file, args.agent)
                    else:
                        manager.override(key, args.file, args.edited, base_sha=args.base_sha)
                output = {"overlay_saved": key + "/" + args.file, "installed_skills_changed": False}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (DuetError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
