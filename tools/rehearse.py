#!/usr/bin/env python3
"""Exercise the public CLI against live Orca using only disposable skill homes."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile

source = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="codex-duet-rehearsal-") as directory:
    root = Path(directory)
    checkout, home = root / "checkout", root / "home"
    checkout.mkdir()
    home.mkdir()
    for name in ("duet.py", "LICENSE", "NOTICE"):
        shutil.copy2(source / name, checkout / name)
    for name in ("catalog", "skills"):
        shutil.copytree(source / name, checkout / name)

    def call(command, *args, failure=False):
        result = subprocess.run(["python3", str(checkout / "duet.py"), command,
                                 "--home", str(home), *args], text=True, capture_output=True)
        if failure:
            assert result.returncode != 0, result.stdout
            return json.loads(result.stderr)
        if result.returncode:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout)

    codex = home / ".agents/skills/codex-duet/SKILL.md"
    claude = home / ".claude/skills/codex-duet/SKILL.md"
    for agent in ("codex", "claude-code"):
        assert call("install", "--profile", "orca", "--agent", agent)[0]["action"] == "install"
        assert call("install", "--profile", "orca", "--agent", agent)[0]["action"] == "unchanged"
    original = codex.read_bytes()
    codex.write_bytes(original + b"\nRehearsal correction.\n")
    call("capture", "--skill", "duet-manager", "--file", "SKILL.md", "--agent", "codex")
    call("install", "--profile", "orca", "--agent", "codex")
    claude.write_bytes(original + b"\nEdit from an older base.\n")
    assert "stale" in call("capture", "--skill", "duet-manager", "--file", "SKILL.md",
                           "--agent", "claude-code", failure=True)["error"]
    assert "Local edits" in call("sync", failure=True)["error"]
    claude.write_bytes(original)  # Revert only the disposable edit created above.
    call("sync")
    assert claude.read_bytes() == codex.read_bytes()
    for agent in ("codex", "claude-code"):
        assert call("status", "--agent", agent)["installed"][0]["state"] == "clean"
        assert call("remove", "--profile", "orca", "--agent", agent) == ["codex-duet"]
        assert call("status", "--agent", agent)["installed"] == []
    print("PASS: live Orca inventory; isolated CLI install, edit, capture, conflict, sync, remove (both agents)")
