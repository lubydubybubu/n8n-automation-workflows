#!/usr/bin/env python3
"""Sanity-check exported n8n workflow JSON before it is committed or imported.

Checks per file:
  * valid JSON object with name, nodes[] and connections{}
  * every node has id/name/type/typeVersion/position and unique names
  * every connection source and target refers to an existing node
  * at least one trigger node; workflow is exported inactive
  * no embedded credentials, Discord webhook URLs, tokens or private IPs/paths
Exit code 1 on any failure. Stdlib only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FORBIDDEN = {
    "discord webhook URL": re.compile(r"discord(?:app)?\.com/api/webhooks/\d+", re.I),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}"),
    "bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"),
    "private IPv4": re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?:\.\d{1,3})?\b"),
    "home path": re.compile(r"/home/[a-z0-9_-]+/", re.I),
}
FORBIDDEN_KEYS = {"credentials", "instanceId", "webhookId"}
REQUIRED_NODE_KEYS = {"id", "name", "type", "typeVersion", "position", "parameters"}


def walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}", k
            yield from walk_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_keys(v, f"{path}[{i}]")


def check(path: Path) -> list[str]:
    errs: list[str] = []
    raw = path.read_text(encoding="utf-8")
    try:
        wf = json.loads(raw)
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"]
    if not isinstance(wf, dict):
        return ["top level is not an object"]
    if not wf.get("name"):
        errs.append("missing name")
    nodes, conns = wf.get("nodes"), wf.get("connections")
    if not isinstance(nodes, list) or not nodes:
        return errs + ["nodes[] missing or empty"]
    if not isinstance(conns, dict) or not conns:
        errs.append("connections{} missing or empty")
        conns = {}
    names = [n.get("name") for n in nodes]
    if len(names) != len(set(names)):
        errs.append("duplicate node names")
    for n in nodes:
        missing = REQUIRED_NODE_KEYS - n.keys()
        if missing:
            errs.append(f"node {n.get('name')!r} missing {sorted(missing)}")
    known = set(names)
    for src, outputs in conns.items():
        if src not in known:
            errs.append(f"connection source {src!r} is not a node")
        for branch in outputs.get("main", []):
            for edge in branch or []:
                if edge.get("node") not in known:
                    errs.append(f"connection {src!r} -> {edge.get('node')!r}: unknown target")
    if not any("trigger" in n.get("type", "").lower() for n in nodes):
        errs.append("no trigger node")
    if wf.get("active") is not False:
        errs.append("workflow must be exported with active=false")
    for p, k in walk_keys(wf):
        if k in FORBIDDEN_KEYS:
            errs.append(f"forbidden key {k!r} at {p}")
    for label, rx in FORBIDDEN.items():
        m = rx.search(raw)
        if m:
            errs.append(f"embedded {label}: {m.group(0)[:12]}…")
    return errs


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv] or sorted(Path("workflows").glob("*.json"))
    if not files:
        print("no workflow files found", file=sys.stderr)
        return 1
    failed = 0
    for f in files:
        errs = check(f)
        if errs:
            failed += 1
            print(f"FAIL {f}")
            for e in errs:
                print(f"  - {e}")
        else:
            wf = json.loads(f.read_text(encoding="utf-8"))
            print(f"ok   {f} ({len(wf['nodes'])} nodes)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
