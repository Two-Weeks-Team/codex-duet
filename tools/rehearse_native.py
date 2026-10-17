#!/usr/bin/env python3
"""Native registration/loading rehearsal. No model turn or memory service is started."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations import Integrations
from duet import ROOT


def skills_list(env, cwd):
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(["codex", "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, env=env, cwd=cwd)
        buffer = b""

        def request(identifier, method, params):
            nonlocal buffer
            process.stdin.write((json.dumps({"id": identifier, "method": method, "params": params}) + "\n").encode())
            process.stdin.flush()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if b"\n" not in buffer:
                    if not select.select([process.stdout], [], [], max(0, deadline - time.monotonic()))[0]:
                        break
                    data = os.read(process.stdout.fileno(), 1024 * 1024)
                    if not data:
                        break
                    buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    message = json.loads(line)
                    if message.get("id") == identifier:
                        if "error" in message:
                            raise RuntimeError(message["error"])
                        return message["result"]
            stderr.seek(0)
            raise RuntimeError("App-server read timed out: " + stderr.read().decode()[-2000:])

        try:
            request(1, "initialize", {"clientInfo": {"name": "codex-duet-validation", "version": "1"},
                                       "capabilities": {"experimentalApi": True}})
            process.stdin.write(b'{"method":"initialized"}\n')
            process.stdin.flush()
            return request(2, "skills/list", {"cwds": [str(cwd)], "forceReload": True})
        finally:
            process.terminate()
            process.wait(timeout=10)


def main():
    with tempfile.TemporaryDirectory(prefix="duet-native-rehearsal-") as directory:
        root = Path(directory)
        checkout, home = root / "checkout", root / "home"
        subprocess.run(["git", "clone", "--shared", "--quiet", str(ROOT), str(checkout)], check=True)
        # Copy the current reviewed worktree, including changes not committed yet.
        paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
        for relative in paths:
            source = ROOT / relative
            if source.is_file():
                target = checkout / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        for source in json.loads((ROOT / "catalog/sources.lock.json").read_text())["sources"].values():
            target = checkout / source["path"]
            subprocess.run(["git", "clone", "--shared", "--quiet", str(ROOT / source["path"]), str(target)], check=True)
            subprocess.run(["git", "checkout", "--quiet", "--detach", source["revision"]], cwd=target, check=True)
        home.mkdir()
        integration = Integrations(checkout, home)
        bundles = list(integration.lock["bundles"])
        # Exercise real registries and real skill parsing, without provisioning
        # dependencies or running observation hooks in a disposable home.
        with patch.object(integration, "prepare_memory"):
            integration.install(bundles, ["codex", "claude-code"], "codex")
        response = skills_list(integration.environment(), home)
        entries = response["data"]
        errors = [error for entry in entries for error in entry["errors"]]
        if errors:
            raise RuntimeError(errors)
        counts = {}
        for entry in entries:
            for skill in entry["skills"]:
                plugin = skill.get("pluginId")
                if plugin and plugin.endswith("@codex-duet"):
                    counts[plugin] = counts.get(plugin, 0) + 1
        if sorted(counts.values()) != [15, 27, 38]:
            raise RuntimeError({"unexpected_plugin_skill_counts": counts, "response": response})
        print("PASS: Codex native loader: " + json.dumps(counts))
        before = integration.marketplace
        record = integration.records()["agents"]["codex"]["mattpocock"]
        relative = "skills/prototype/SKILL.md"
        edited = Path(record["install_path"]) / relative
        edited.write_bytes(edited.read_bytes() + b"\nNative rehearsal correction.\n")
        integration.capture("mattpocock", relative, "codex")
        integration = Integrations(checkout, home)
        assert integration.marketplace == before, "marketplace address changed during an update"
        integration.install(["mattpocock"], ["codex", "claude-code"])
        for agent in ("codex", "claude-code"):
            record = integration.records()["agents"][agent]["mattpocock"]
            actual = Path(record["install_path"]) / relative
            assert b"Native rehearsal correction." in actual.read_bytes(), agent
        print("PASS: captured overlay upgrades both native plugins through a stable marketplace")
        integration.remove(bundles, ["codex", "claude-code"])
        print("PASS: both native registries install/remove; no model calls, hooks or memory runtime executed")


if __name__ == "__main__":
    main()
