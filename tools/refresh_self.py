#!/usr/bin/env python3
"""Refresh hashes of already-allowlisted original files after editing this project."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "catalog/skills.json"
catalog = json.loads(path.read_text())
for component in catalog["skills"].values():
    if component["source"] == "self":
        for relative in component["files"]:
            source = root / component["path"] / relative
            component["files"][relative] = hashlib.sha256(source.read_bytes()).hexdigest()
path.write_text(json.dumps(catalog, indent=2) + "\n")
