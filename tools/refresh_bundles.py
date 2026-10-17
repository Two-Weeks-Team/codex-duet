#!/usr/bin/env python3
"""Review hash/mode changes to existing native allowlists after a source pin update."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from duet import DuetError, Manager, digest, load, save, safe
from integrations import Integrations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", choices=("mattpocock", "superpowers", "claude-mem"))
    parser.add_argument("--write", action="store_true", help="Write the reviewed hashes of existing files only")
    args = parser.parse_args()
    manager = Manager()
    path = manager.root / "catalog/bundles.lock.json"
    with manager.locked():
        candidate = copy.deepcopy(load(path))
        changes = []
        pins = []
        for key in args.source or candidate["bundles"]:
            manager.verify_source(key)
            source, bundle = manager.sources[key], candidate["bundles"][key]
            if bundle["revision"] != source["revision"]:
                pins.append({"source": key, "before": bundle["revision"], "after": source["revision"]})
            base = safe(manager.root, source["path"])
            listing = subprocess.check_output(["git", "ls-files", "--stage"], cwd=base, text=True)
            modes = {line.split("\t", 1)[1]: line.split()[0] for line in listing.splitlines()}
            for relative, item in bundle["files"].items():
                sha = digest(safe(base, item["from"]).read_bytes())
                mode = modes[item["from"]]
                if sha != item["sha256"] or mode != item["mode"]:
                    if relative in bundle.get("overlays", {}):
                        raise DuetError(f"Rebase the native overlay explicitly first: {key}/{relative}")
                    if relative in bundle.get("patches", {}):
                        raise DuetError(f"Review and regenerate the version-bound runtime patch first: {key}/{relative}")
                    changes.append({"source": key, "file": relative, "before": item["sha256"], "after": sha,
                                    "mode_before": item["mode"], "mode_after": mode})
                    item.update(sha256=sha, mode=mode)
            bundle["revision"] = source["revision"]
        integration = Integrations()
        integration.lock = candidate
        for key in args.source or candidate["bundles"]:
            integration.rendered(key)
        if args.write:
            save(path, candidate)
        print(json.dumps({"written": args.write, "pins": pins, "changes": changes,
                          "note": "No new files approved. Review revision, license surface, hashes and modes before committing."}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (DuetError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        sys.exit(1)
