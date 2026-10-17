#!/usr/bin/env python3
"""Pinned native plugins for Orca's Codex and Claude, including local memory."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

from duet import Manager, DuetError, ROOT, digest, inventory, load, save, safe, orca_check


MARKET = "codex-duet"
AGENTS = ("codex", "claude-code")
RENDER_VERSION = 6


def command(argv, *, cwd=None, env=None):
    """Native registries own their caches; never edit their private file formats."""
    print("Running: " + shlex.join(map(str, argv)), file=sys.stderr, flush=True)
    result = subprocess.run(list(map(str, argv)), cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise DuetError(f"Command failed ({result.returncode}): {shlex.join(map(str, argv))}\n"
                        + result.stderr[-6000:] + result.stdout[-6000:])
    return result.stdout.strip()


class Integrations:
    def __init__(self, root=ROOT, home=None):
        self.manager = Manager(root, home)
        self.root, self.home = self.manager.root, self.manager.home
        self.lock = load(self.root / "catalog/bundles.lock.json")
        self.receipt = self.manager.state / "native-installations.json"
        self.share = safe(self.home, ".local/share/codex-duet-managed/native")
        self.identity = digest(json.dumps([RENDER_VERSION, self.lock], sort_keys=True).encode())[:20]
        self.marketplace = self.share
        self.payload_root = self.share / self.identity
        self.runtime = self.share.parent / "runtime" / self.identity

    def backup_settings(self):
        destination = safe(self.manager.state, "backups/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        destination.mkdir(parents=True, mode=0o700)
        existed = []
        for relative in (".codex/config.toml", ".claude/settings.json", ".claude/plugins/installed_plugins.json",
                         ".claude/plugins/known_marketplaces.json", ".claude-mem/settings.json", ".claude-mem/telemetry.json",
                         ".local/state/codex-duet/installations.json", ".local/state/codex-duet/native-installations.json"):
            path = safe(self.home, relative)
            if path.is_file():
                target = safe(destination, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                target.chmod(0o600)
                existed.append(relative)
        save(destination / "manifest.json", {"existed": existed,
             "note": "Private settings snapshot; restore only reviewed keys, not whole files over newer changes."})
        return str(destination)

    def records(self):
        safe(self.manager.state, self.receipt.name)
        return load(self.receipt) if self.receipt.exists() else {"schema": 1, "agents": {}}

    def payload(self, key):
        bundle = self.lock["bundles"][key]
        self.manager.verify_source(bundle["source"])
        source = self.manager.sources[bundle["source"]]
        if source["revision"] != bundle["revision"]:
            raise DuetError(f"Bundle pin changed: {key}; review its exact file filter again.")
        base = safe(self.root, source["path"])
        output = {}
        for relative, item in bundle["files"].items():
            data = safe(base, item["from"]).read_bytes()
            if digest(data) != item["sha256"]:
                raise DuetError(f"Bundle file drift: {key}/{relative}")
            if item["mode"] not in ("100644", "100755"):
                raise DuetError(f"Unsupported file mode: {key}/{relative}")
            safe(Path("/bundle"), relative)
            overlay = bundle.get("overlays", {}).get(relative)
            if overlay:
                if overlay["base_sha256"] != item["sha256"]:
                    raise DuetError(f"Bundle overlay base changed: {key}/{relative}")
                data = safe(self.root, overlay["path"]).read_bytes()
                if digest(data) != overlay["sha256"]:
                    raise DuetError(f"Bundle overlay drift: {key}/{relative}")
            patch = bundle.get("patches", {}).get(relative)
            if patch:
                recipe_data = safe(self.root, patch["path"]).read_bytes()
                if digest(recipe_data) != patch["sha256"] or digest(data) != patch["base_sha256"]:
                    raise DuetError(f"Native runtime patch base/recipe changed: {key}/{relative}")
                recipe = json.loads(recipe_data)
                replacement = safe(self.root, recipe["replacement_path"]).read_bytes()
                if digest(replacement) != recipe["replacement_sha256"]:
                    raise DuetError(f"Native runtime replacement changed: {relative}")
                text = data.decode()
                if text.count(recipe["start"]) != 1 or text.count(recipe["end"]) != 1:
                    raise DuetError(f"Native runtime patch boundaries changed: {relative}")
                start, end = text.index(recipe["start"]), text.index(recipe["end"])
                if end <= start or digest(text[start:end].encode()) != recipe["before_sha256"]:
                    raise DuetError(f"Native runtime patch section changed: {relative}")
                original = b""
                if recipe.get("preserve_original_as"):
                    original = (text[start:end].replace("var oj=class{", "var " + recipe["preserve_original_as"] + "=class{", 1) + ";\n").encode()
                data = text[:start].encode() + original + replacement + text[end:].encode()
                if digest(data) != patch["result_sha256"]:
                    raise DuetError(f"Native runtime patch output changed: {relative}")
            output[relative] = data
        return output

    def plugin_root(self, key):
        return self.payload_root / "plugins" / self.lock["bundles"][key]["name"]

    def rendered(self, key):
        output = self.payload(key)
        bundle = self.lock["bundles"][key]
        if key == "mattpocock":
            # Flatten category directories for native discovery on both hosts.
            manifest = json.loads(output[".claude-plugin/plugin.json"])
            manifest["skills"] = "./skills/"
            output[".claude-plugin/plugin.json"] = json_bytes(manifest)
            manifest["hooks"] = "./hooks/hooks.json"
            output[".codex-plugin/plugin.json"] = json_bytes(manifest)
            adapter = "adapters/orca-bootstrap.py"
            data = safe(self.root, adapter).read_bytes()
            if digest(data) != self.lock.get("adapter_files", {}).get(adapter):
                raise DuetError("Orca bootstrap changed; review its adapter hash before installation.")
            output["hooks/orca-bootstrap.py"] = data
            output["hooks/hooks.json"] = json_bytes({"hooks": {"SessionStart": [{
                "matcher": "startup|resume|clear|compact", "hooks": [{"type": "command",
                    "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/orca-bootstrap.py"', "timeout": 10}]}]}})
        if key == "superpowers":
            # Upstream's Codex manifest currently disables its bootstrap.
            manifest = json.loads(output[".codex-plugin/plugin.json"])
            manifest["hooks"] = "./hooks/hooks.json"
            output[".codex-plugin/plugin.json"] = json_bytes(manifest)
        if key == "claude-mem":
            # Both hosts use one dependency installation and one local worker.
            # Absolute paths are generated in the user's state, never committed.
            plugin = self.runtime
            runner = ["/bin/sh", str(plugin / "bin/node-run.sh"), str(plugin / "scripts/claude-mem-launcher.cjs")]
            for relative, platform in (("hooks/hooks.json", "claude-code"),
                                       ("hooks/codex-hooks.json", "codex")):
                hooks = json.loads(output[relative])
                for event, groups in hooks["hooks"].items():
                    if event == "Setup":
                        continue
                    for group in groups:
                        for hook in group["hooks"]:
                            args = hook.pop("args", None)
                            if args is None:
                                # Codex's generated resolver ends in a typed hook call.
                                match = re.search(r"hook codex ([a-z-]+)$", hook["command"])
                                if not match:
                                    raise DuetError(f"Unreviewed memory hook event: {event}")
                                args = ["hook", platform, match.group(1)]
                            if "ensure-launcher.cjs" in " ".join(args):
                                hook["command"] = shlex.join([*runner, "--version"])
                            else:
                                environment = ["env", f"CLAUDE_PLUGIN_ROOT={plugin}"]
                                if platform == "codex":
                                    environment.append("CLAUDE_MEM_CODEX_HOOK=1")
                                hook["command"] = shlex.join([*environment, *runner, *args])
                            hook.pop("commandWindows", None)
                hooks["hooks"].pop("Setup", None)  # Dependencies are an explicit installer step.
                output[relative] = json_bytes(hooks)
            output[".mcp.json"] = json_bytes({"mcpServers": {"mcp-search": {
                "type": "stdio", "command": "/bin/sh",
                "args": [str(plugin / "bin/node-run.sh"), str(plugin / "scripts/mcp-server.cjs")],
                "env": {"CLAUDE_PLUGIN_ROOT": str(plugin)}}}})
            # Claude's registry otherwise auto-installs a second dependency tree
            # in its cache. All executable entrypoints use our shared runtime.
            output.pop("package.json")
            output.pop("bun.lock")
        # Distinct adapted versions keep native cache upgrades reversible.
        for relative in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
            manifest = json.loads(output[relative])
            manifest["version"] = manifest["version"] + "-duet." + self.identity[:8]
            output[relative] = json_bytes(manifest)
        output[".duet-origin.json"] = json_bytes({"source": self.manager.sources[key]["url"],
            "revision": bundle["revision"], "filter": "catalog/bundles.lock.json",
            "adaptations": "docs/integrations.md", "skill_count": sum(
                path.endswith("/SKILL.md") for path in output)})
        return output

    def external_claude(self, key):
        """Reuse only an enabled native plugin at the exact pinned Git commit."""
        path = self.home / ".claude/plugins/installed_plugins.json"
        settings_path = self.home / ".claude/settings.json"
        if not path.exists() or not settings_path.exists():
            return None
        settings = load(settings_path)
        name = self.lock["bundles"][key]["name"]
        for selector, installs in load(path).get("plugins", {}).items():
            if selector.split("@")[0] != name or not settings.get("enabledPlugins", {}).get(selector):
                continue
            if selector == f"{name}@{MARKET}":
                continue
            for entry in installs:
                if entry.get("scope") != "user":
                    continue
                if entry.get("gitCommitSha") != self.lock["bundles"][key]["revision"]:
                    raise DuetError(f"Existing {selector} has another pin; resolve it before native installation.")
                base = Path(entry["installPath"])
                # Verify operational skill/hook bytes, not registry metadata alone.
                for rel, data in self.payload(key).items():
                    if rel.startswith(("skills/", "hooks/", "agents/")):
                        p = safe(base, rel)
                        if not p.is_file() or p.read_bytes() != data:
                            raise DuetError(f"Existing {selector} payload differs: {rel}")
                return {"selector": selector, "path": str(base), "revision": entry["gitCommitSha"]}
        return None

    def registry(self, agent):
        if agent == "codex":
            if not safe(self.home, ".codex").exists():
                return {}
            data = json.loads(command(["codex", "plugin", "list", "--json"], env=self.environment()))
            return {entry["pluginId"]: entry for entry in data.get("installed", [])}
        registry_path = safe(self.home, ".claude/plugins/installed_plugins.json")
        settings_path = safe(self.home, ".claude/settings.json")
        plugins = load(registry_path).get("plugins", {}) if registry_path.exists() else {}
        enabled = load(settings_path).get("enabledPlugins", {}) if settings_path.exists() else {}
        return {selector: {"enabled": enabled.get(selector, False), "installs": installs}
                for selector, installs in plugins.items() if any(p.get("scope") == "user" for p in installs)}

    def plan(self, selected, agents):
        records = self.records()
        registries = {agent: self.registry(agent) for agent in agents}
        rows = []
        for key in selected:
            payload = self.rendered(key)
            for agent in agents:
                external = self.external_claude(key) if agent == "claude-code" else None
                old = records["agents"].get(agent, {}).get(key)
                selector = self.lock["bundles"][key]["name"] + "@" + MARKET
                if not old and selector in registries[agent]:
                    raise DuetError(f"Native plugin {selector} is not in Duet's receipt; preserve it and resolve ownership before installation.")
                if agent == "codex":
                    conflicts = [s for s in registries[agent] if s.split("@")[0] == selector.split("@")[0] and s != selector]
                    if conflicts:
                        raise DuetError(f"Existing native Codex plugin would duplicate {key}: {conflicts}. Preserve it and resolve the selection first.")
                if old and not old.get("external"):
                    self.check_owned(old, {p: digest(b) for p, b in payload.items()})
                for record in self.manager.records()["agents"].get(agent, {}).values():
                    component = self.manager.catalog["skills"].get(record["component"], {})
                    if component.get("source") == key:
                        raise DuetError(f"Remove the selective {record['component']} installation from {agent} before enabling its complete native plugin.")
                rows.append({"bundle": key, "name": self.lock["bundles"][key]["name"],
                    "agent": agent, "revision": self.lock["bundles"][key]["revision"],
                    "skills": sum(p.endswith("/SKILL.md") for p in payload),
                    "action": "reuse-existing" if external else (
                        "unchanged" if old and old.get("identity") == self.identity
                        and registries[agent].get(selector, {}).get("enabled") else "install"),
                    "external": external, "files": len(payload)})
        return rows

    def stage(self, selected):
        self.marketplace.mkdir(parents=True, exist_ok=True)
        for key in selected:
            output = self.rendered(key)
            target = self.plugin_root(key)
            if target.exists():
                if inventory(target) != {rel: digest(data) for rel, data in output.items()}:
                    raise DuetError(f"Native staging changed: {target}. Preserve local edits before reapplying.")
                for relative, data in output.items():
                    p = safe(target, relative)
                    if not p.is_file() or p.read_bytes() != data:
                        raise DuetError(f"Local native bundle edit: {p}. Preserve it before updating.")
                    expected_mode = self.lock["bundles"][key]["files"].get(relative, {}).get("mode", "100644")
                    if bool(p.stat().st_mode & 0o111) != (expected_mode == "100755"):
                        raise DuetError(f"Native staging executable mode changed: {p}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".duet-", dir=target.parent) as directory:
                candidate = Path(directory) / "new"
                candidate.mkdir()
                for relative, data in output.items():
                    path = safe(candidate, relative)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    mode = self.lock["bundles"][key]["files"].get(relative, {}).get("mode", "100644")
                    path.chmod(0o755 if mode == "100755" else 0o644)
                candidate.rename(target)
        manifest_path = self.marketplace / ".claude-plugin/marketplace.json"
        previous = load(manifest_path).get("plugins", []) if manifest_path.exists() else []
        locations = {item["name"]: item["source"] for item in previous}
        for key in selected:
            name = self.lock["bundles"][key]["name"]
            locations[name] = f"./{self.identity}/plugins/{name}"
        save(self.marketplace / ".claude-plugin/marketplace.json", {
            "name": MARKET, "owner": {"name": "Codex Duet"}, "plugins": [
                {"name": name, "source": path} for name, path in sorted(locations.items())]})
        save(self.marketplace / ".agents/plugins/marketplace.json", {
            "name": MARKET, "interface": {"displayName": "Codex Duet (pinned)"}, "plugins": [
                {"name": name, "source": {"source": "local", "path": path},
                 "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}}
                for name, path in sorted(locations.items())]})

    def environment(self):
        env = os.environ.copy()
        if self.home != Path.home().resolve():
            env.update(HOME=str(self.home), CODEX_HOME=str(self.home / ".codex"),
                       CLAUDE_CONFIG_DIR=str(self.home / ".claude"))
        return env

    def install(self, selected, agents, provider=None):
        live = orca_check()
        self.plan(selected, agents)
        if "claude-mem" in selected and provider is None:
            raise DuetError("Memory requires --provider claude/codex (existing subscription) or manual (already configured API provider).")
        manager_selection = self.manager.selection("orca", [])
        for agent in agents:
            self.manager.plan(manager_selection, agent, live)
        backup = self.backup_settings()
        for agent in agents:
            self.manager.install(manager_selection, agent, live)
            safe(self.home, ".codex" if agent == "codex" else ".claude").mkdir(parents=True, exist_ok=True)
        with self.manager.locked():
            rows = self.plan(selected, agents)
            # Preflight all conflicts before registration; each registry is its own transaction.
            self.stage(selected)
            if "claude-mem" in selected:
                self.prepare_memory(provider)
            records = self.records()
            records["latest_settings_backup"] = backup
            if "claude-mem" in selected:
                records["memory_provider"] = provider
            for agent in agents:
                pending = [r for r in rows if r["agent"] == agent and not r["external"]]
                if pending:
                    binary = "codex" if agent == "codex" else "claude"
                    command([binary, "plugin", "marketplace", "add", str(self.marketplace), "--json"], env=self.environment())
                    if agent == "claude-code":
                        command([binary, "plugin", "marketplace", "update", MARKET, "--json"], env=self.environment())
                for row in [r for r in rows if r["agent"] == agent]:
                    key, name = row["bundle"], row["name"]
                    install_path = None
                    if not row["external"] and row["action"] != "unchanged":
                        verb = "add" if agent == "codex" else (
                            "update" if key in records["agents"].get(agent, {}) else "install")
                        response = json.loads(command([binary, "plugin", verb, f"{name}@{MARKET}", "--json"], env=self.environment()))
                        if agent == "codex":
                            install_path = response["installedPath"]
                        else:
                            installs = load(self.home / ".claude/plugins/installed_plugins.json")["plugins"][f"{name}@{MARKET}"]
                            install_path = next(r["installPath"] for r in installs if r.get("scope") == "user")
                    elif row["action"] == "unchanged":
                        install_path = records["agents"][agent][key]["install_path"]
                    records["agents"].setdefault(agent, {})[key] = {
                        "name": name, "revision": row["revision"], "marketplace": str(self.marketplace),
                        "identity": self.identity,
                        "external": row["external"], "install_path": install_path,
                        "executable": sorted(p for p, item in self.lock["bundles"][key]["files"].items()
                                             if item["mode"] == "100755" and p in self.rendered(key)),
                        "files": {p: digest(b) for p, b in self.rendered(key).items()}}
                    if not row["external"]:
                        self.check_owned(records["agents"][agent][key])
                    save(self.receipt, records)
            return rows

    def memory_settings(self, provider, switch=False):
        settings_path = safe(self.home, ".claude-mem/settings.json")
        settings = load(settings_path) if settings_path.exists() else {}
        if provider in ("codex", "claude"):
            current = settings.get("CLAUDE_MEM_PROVIDER")
            if current not in (None, provider) and not switch:
                raise DuetError(f"Existing memory provider {current} was preserved; configure it explicitly.")
            settings["CLAUDE_MEM_PROVIDER"] = provider
        elif not settings.get("CLAUDE_MEM_PROVIDER"):
            raise DuetError("Manual provider requires an existing configured memory provider. No default Claude subprocess is enabled.")
        policy = {"CLAUDE_MEM_WORKER_HOST": "127.0.0.1", "CLAUDE_MEM_QUOTA_FALLBACK_PROVIDER": "off",
                  "CLAUDE_MEM_FILE_READ_GATE_ENABLED": "false", "CLAUDE_MEM_REDACT_ENABLED": "true",
                  "CLAUDE_MEM_REDACT_GENERIC_ENABLED": "true"}
        for key, expected in policy.items():
            if key in settings and str(settings[key]).lower() != expected:
                raise DuetError(f"Existing {key} conflicts with the Orca memory policy; it was preserved. Review that setting explicitly.")
            settings[key] = expected
        for key in (*policy, "CLAUDE_MEM_PROVIDER"):
            if key in os.environ and str(os.environ[key]).lower() != settings[key]:
                raise DuetError(f"Environment override {key} conflicts with the reviewed memory settings.")
        if os.environ.get("CLAUDE_MEM_TELEMETRY", "0").lower() not in ("0", "false", "off"):
            raise DuetError("Environment enables CLAUDE_MEM_TELEMETRY; disable it before starting memory.")
        telemetry_path = safe(self.home, ".claude-mem/telemetry.json")
        if telemetry_path.exists() and load(telemetry_path).get("enabled") is not False:
            raise DuetError("Existing telemetry preference conflicts with Duet's opt-out; it was preserved. Review it explicitly.")
        codex = shutil.which("codex")
        if provider == "codex" and not codex:
            raise DuetError("Codex CLI is required for the selected memory provider.")
        if settings.get("CLAUDE_MEM_CODEX_PATH") in (None, "codex") and codex:
            settings["CLAUDE_MEM_CODEX_PATH"] = codex
        settings.setdefault("CLAUDE_MEM_SESSION_START_INCLUDE_ALL_SOURCES", "true")
        settings.setdefault("CLAUDE_MEM_SEMANTIC_INJECT", "true")
        return settings

    def configure_memory(self, provider):
        if not provider:
            raise DuetError("Choose --provider claude, codex or manual explicitly.")
        with self.manager.locked():
            settings = self.memory_settings(provider, switch=True)
            backup = self.backup_settings()
            save(safe(self.home, ".claude-mem/settings.json"), settings)
            records = self.records()
            records["memory_provider"] = provider
            records["latest_settings_backup"] = backup
            save(self.receipt, records)
        return {"provider": settings["CLAUDE_MEM_PROVIDER"], "restart_required": True}

    def prepare_memory(self, provider):
        settings = self.memory_settings(provider)
        if not shutil.which("bun") or not shutil.which("node"):
            raise DuetError("Memory requires Node >=20.12 and Bun >=1.1.31; install those runtimes first.")
        plugin = self.runtime
        output = self.payload("claude-mem")
        adapter = "adapters/node-run.sh"
        wrapper = safe(self.root, adapter).read_bytes()
        if digest(wrapper) != self.lock.get("adapter_files", {}).get(adapter):
            raise DuetError("Node wrapper changed; review its adapter hash first.")
        output["bin/node-run.sh"] = wrapper
        if plugin.exists():
            for relative, data in output.items():
                p = safe(plugin, relative)
                if not p.is_file() or p.read_bytes() != data:
                    raise DuetError(f"Local memory runtime edit: {p}. Preserve it before updating.")
        else:
            plugin.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".duet-", dir=plugin.parent) as directory:
                candidate = Path(directory) / "new"
                candidate.mkdir()
                for relative, data in output.items():
                    p = safe(candidate, relative)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(data)
                    mode = self.lock["bundles"]["claude-mem"]["files"].get(relative, {}).get("mode", "100755" if relative.endswith(".sh") else "100644")
                    p.chmod(0o755 if mode == "100755" else 0o644)
                candidate.rename(plugin)
        command(["bun", "install", "--frozen-lockfile"], cwd=plugin, env=self.environment())
        settings_path = safe(self.home, ".claude-mem/settings.json")
        save(settings_path, settings)
        telemetry_path = safe(self.home, ".claude-mem/telemetry.json")
        if not telemetry_path.exists():
            save(telemetry_path, {"enabled": False, "installId": str(uuid.uuid4()),
                                 "decidedAt": datetime.now(timezone.utc).isoformat()})

    def shutdown_memory(self, url):
        # A successful shutdown may close the socket before the response flushes.
        # The caller has already verified the worker path and ownership.
        request = urllib.request.Request(url + "/api/admin/shutdown", data=b"{}", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10):
                pass
        except (urllib.error.URLError, ConnectionError):
            pass
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=1):
                    pass
            except (urllib.error.URLError, ConnectionError):
                return
            time.sleep(0.2)
        raise DuetError("Owned memory worker did not confirm shutdown; no replacement was started.")

    def memory_command(self, verb):
        with self.manager.locked():
            return self._memory_command(verb)

    def _memory_command(self, verb):
        plugin = self.runtime
        if not plugin.exists():
            raise DuetError("Memory runtime is not installed. Install its native bundle first.")
        env = self.environment()
        if verb == "stop":
            records = self.records()
            active = records.get("active_runtime")
            if not active:
                if not any("claude-mem" in entries for entries in records["agents"].values()):
                    raise DuetError("No Duet-owned active memory runtime is recorded; an external worker was preserved.")
                active = str(plugin)
            port = int(records.get("active_port", 37700 + os.getuid() % 100))
            url = f"http://127.0.0.1:{port}"
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=3) as response:
                    health = json.load(response)
            except urllib.error.URLError:
                return json.dumps({"status": "not-running"})
            if health.get("workerPath") != str(Path(active) / "scripts/worker-service.cjs"):
                raise DuetError("The running memory worker is not Duet-owned; it was preserved.")
            self.shutdown_memory(url)
            records["active_runtime"] = None
            save(self.receipt, records)
            return json.dumps({"status": "stopped"})
        if verb in ("start", "restart"):
            settings = self.memory_settings(self.records().get("memory_provider", "codex"))
            port = int(settings.get("CLAUDE_MEM_WORKER_PORT", 37700 + os.getuid() % 100))
            url = f"http://127.0.0.1:{port}"
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=3) as response:
                    health = json.load(response)
            except urllib.error.URLError:
                health = None
            if health and health.get("workerPath") != str(plugin / "scripts/worker-service.cjs"):
                active = self.records().get("active_runtime")
                if not active or health.get("workerPath") != str(Path(active) / "scripts/worker-service.cjs"):
                    raise DuetError("Another memory runtime owns this port. Preserve it and resolve ownership before starting Duet memory.")
                self.shutdown_memory(url)
        env["CLAUDE_PLUGIN_ROOT"] = str(plugin)
        result = command(["bun", plugin / "scripts/worker-service.cjs", verb], env=env)
        if verb in ("start", "restart"):
            with urllib.request.urlopen(url + "/api/health", timeout=10) as response:
                health = json.load(response)
            if health.get("workerPath") != str(plugin / "scripts/worker-service.cjs"):
                raise DuetError("Memory started from an unexpected runtime; active ownership was not adopted.")
            records = self.records()
            records["active_runtime"] = str(plugin)
            records["active_port"] = port
            save(self.receipt, records)
        return result

    def status(self, agents):
        result = {}
        for agent in agents:
            registered = self.registry(agent)
            rows = []
            for key, record in self.records()["agents"].get(agent, {}).items():
                if record.get("external"):
                    live = self.external_claude(key)
                    state = "external-verified" if live == record["external"] else "external-changed"
                else:
                    try:
                        self.check_owned(record)
                        state = "installed-files-verified"
                    except DuetError:
                        state = "modified-or-missing"
                rows.append({"bundle": key, "state": state, "revision": record["revision"],
                             "native_registration": registered.get(
                                 record["external"]["selector"] if record.get("external") else record["name"] + "@" + MARKET,
                                 {}).get("enabled", False)})
            result[agent] = rows
        return result

    def check_owned(self, record, desired=None):
        target = Path(record["install_path"])
        actual = inventory(target) if target.is_dir() else None
        reviewed = (actual is not None and desired is not None and set(actual) == set(record["files"])
                    and all(sha in (record["files"].get(p), desired.get(p)) for p, sha in actual.items()))
        if actual != record["files"] and not reviewed:
            raise DuetError(f"Native installed files changed: {target}. Preserve edits before updating or removing.")
        if "executable" in record and any(bool(safe(target, rel).stat().st_mode & 0o111) !=
                                          (rel in record["executable"]) for rel in record["files"]):
            raise DuetError(f"Native installed executable modes changed: {target}. Preserve edits before updating or removing.")

    def capture(self, key, relative, agent):
        with self.manager.locked():
            # Reload the native catalog inside the same host state lock.
            self.lock = load(self.root / "catalog/bundles.lock.json")
            bundle = self.lock["bundles"][key]
            if relative not in bundle["files"] or relative in bundle.get("patches", {}) or relative.startswith((".codex-plugin/", ".claude-plugin/", "hooks/", ".mcp.json")):
                raise DuetError("Capture only source payload files; generated native manifests/hooks require editing the adapter.")
            record = self.records()["agents"].get(agent, {}).get(key)
            if not record or record.get("external"):
                raise DuetError("Native capture requires a Duet-owned installation, not an external plugin.")
            expected = digest(self.rendered(key)[relative])
            if record["files"].get(relative) != expected:
                raise DuetError("Native edit base is stale. Rebase against the current bundle before capturing.")
            edited = safe(Path(record["install_path"]), relative)
            data = edited.read_bytes()
            path = f"overlays/native/{key}/{relative}"
            target = safe(self.root, path)
            previous = bundle.get("overlays", {}).get(relative)
            if target.exists() and (not previous or digest(target.read_bytes()) != previous["sha256"]):
                raise DuetError("Unregistered native overlay edits exist; preserve them before capture.")
            before = self.root.joinpath("catalog/bundles.lock.json").read_bytes()
            old_data = target.read_bytes() if target.exists() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            bundle.setdefault("overlays", {})[relative] = {"path": path,
                "base_sha256": bundle["files"][relative]["sha256"], "sha256": digest(data)}
            try:
                self.payload(key)
                save(self.root / "catalog/bundles.lock.json", self.lock)
            except BaseException:
                self.root.joinpath("catalog/bundles.lock.json").write_bytes(before)
                if old_data is None:
                    target.unlink()
                else:
                    target.write_bytes(old_data)
                raise
            return {"overlay_saved": path, "installed_plugins_changed": False,
                    "next": "Reapply this native bundle to adopt the reviewed edit."}

    def sync(self):
        records = self.records()
        result = {}
        for agent, bundles in records["agents"].items():
            if bundles:
                self.plan(list(bundles), [agent])
        for agent, bundles in records["agents"].items():
            if bundles:
                result[agent] = self.install(list(bundles), [agent], records.get("memory_provider"))
        return result

    def remove(self, selected, agents):
        with self.manager.locked():
            records = self.records()
            removed = []
            for agent in agents:
                for key in selected:
                    record = records["agents"].get(agent, {}).get(key)
                    if not record:
                        continue
                    if not record.get("external"):
                        self.check_owned(record)
                        binary, verb = ("codex", "remove") if agent == "codex" else ("claude", "uninstall")
                        command([binary, "plugin", verb, f"{record['name']}@{MARKET}"], env=self.environment())
                    del records["agents"][agent][key]
                    save(self.receipt, records)
                    removed.append({"agent": agent, "bundle": key, "external_preserved": bool(record.get("external"))})
            return {"removed": removed, "memory_data_preserved": True,
                    "note": "Pinned staging and dependencies retained for rollback. Stop memory separately when no host needs it."}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "verify", "install", "sync", "status", "remove", "capture", "configure-memory", "memory-start", "memory-restart", "memory-stop", "memory-status"))
    parser.add_argument("--bundle", action="append", choices=("mattpocock", "superpowers", "claude-mem"))
    parser.add_argument("--agent", choices=(*AGENTS, "both"), default="both")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--provider", choices=("claude", "codex", "manual"))
    parser.add_argument("--file")
    args = parser.parse_args()
    try:
        integration = Integrations(home=args.home)
        selected = args.bundle or list(integration.lock["bundles"])
        agents = list(AGENTS) if args.agent == "both" else [args.agent]
        if args.command == "plan":
            output = integration.plan(selected, agents)
        elif args.command == "verify":
            output = {key: len(integration.rendered(key)) for key in selected}
        elif args.command == "install":
            output = integration.install(selected, agents, args.provider)
        elif args.command == "status":
            output = integration.status(agents)
        elif args.command == "remove":
            output = integration.remove(selected, agents)
        elif args.command == "capture":
            if len(selected) != 1 or args.agent == "both" or not args.file:
                raise DuetError("Capture requires one --bundle, one --agent, and --file RELATIVE.")
            output = integration.capture(selected[0], args.file, args.agent)
        elif args.command == "sync":
            output = integration.sync()
        elif args.command == "configure-memory":
            output = integration.configure_memory(args.provider)
        else:
            output = {"worker": integration.memory_command(args.command.removeprefix("memory-"))}
        print(json.dumps(output, indent=2))
        return 0
    except (DuetError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
