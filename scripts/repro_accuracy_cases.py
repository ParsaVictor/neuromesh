#!/usr/bin/env python3
"""Reproduce the four known fast-engine accuracy cases over MCP."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

CASES = [
    (
        "dangerous-paths",
        "How does this tool prevent indexing dangerous paths like the filesystem root?",
        ["crates/neuromesh-index/src/confine.rs"],
    ),
    (
        "importance-reinforce",
        "How does a file's importance get reinforced after repeated edits?",
        [
            "crates/neuromesh-router/src/predictor.rs",
            "crates/neuromesh-memory/src",
            "crates/neuromesh-graph/src/synapse.rs",
        ],
    ),
    (
        "retry-backoff-absent",
        "Is there retry logic or exponential backoff when calling the AI provider API?",
        [],  # should be no_confident_match, not a random hit
    ),
    (
        "max-files-auto",
        "How does the system determine the maximum number of files to index automatically?",
        [
            "crates/neuromesh-index/src/walker.rs",
            "crates/neuromesh-core/src/config.rs",
            "crates/neuromesh-cli/src",
        ],
    ),
]


def run(bin_path: str, detail: str | None) -> None:
    env = os.environ.copy()
    for k in ["WORKSPACE_FOLDER_PATHS", "VSCODE_CWD", "NEUROMESH_WORKSPACE", "PWD"]:
        env.pop(k, None)
    proc = subprocess.Popen(
        [bin_path, "mcp", r"C:\projects\neuromesh"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=r"C:\projects\neuromesh",
        env=env,
        bufsize=0,
    )
    q: queue.Queue = queue.Queue()
    pending: dict[int, dict] = {}

    def pump(s, lab):
        for raw in iter(s.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if lab == "o" and line.strip():
                q.put(line)

    threading.Thread(target=pump, args=(proc.stdout, "o"), daemon=True).start()
    threading.Thread(target=pump, args=(proc.stderr, "e"), daemon=True).start()

    def send(obj):
        assert proc.stdin
        proc.stdin.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        proc.stdin.flush()

    def wait(rid, t=40):
        end = time.time() + t
        while time.time() < end and rid not in pending:
            try:
                line = q.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None:
                    return False
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == rid:
                pending[rid] = msg
        return rid in pending

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "acc-repro", "version": "1"},
    }})
    wait(1)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    rid = 10
    for name, prompt, expected in CASES:
        args = {"task": prompt}
        if detail:
            args["response_detail"] = detail
        send({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
              "params": {"name": "get_context_packet", "arguments": args}})
        if not wait(rid):
            print(f"{name}: TIMEOUT")
            rid += 1
            continue
        text = pending.pop(rid)["result"]["content"][0]["text"]
        data = json.loads(text)
        # diagnostic nests under evidence_packet
        src = data.get("evidence_packet") or data
        files = []
        for f in src.get("files") or data.get("files") or []:
            if isinstance(f, dict):
                files.append(f.get("path"))
            else:
                files.append(str(f))
        cov = src.get("coverage") or data.get("coverage")
        claim = cov.get("claim") if isinstance(cov, dict) else cov
        ret = src.get("retrieval") or data.get("retrieval") or {}
        tier = data.get("resolution_tier") or ret.get("resolution_tier")
        conf = data.get("confidence") or ret.get("confidence")
        suff = ret.get("sufficiency_score")
        hit = any(any(e in (p or "") for e in expected) for p in files) if expected else False
        weak = tier == "no_confident_match" or (
            conf is not None and conf < 0.5 and claim in ("bounded", "no_recorded_gap", "likely_sufficient")
        )
        if expected and hit:
            status = "HIT"
        elif not expected and (claim in ("no_seed_resolved", "no_confident_match") or weak):
            status = "OK-weak" if files else "OK-empty"
        else:
            status = "MISS"
        print(f"[{status}] {name}")
        print(f"  claim={claim} tier={tier} conf={conf} suff={suff}")
        print(f"  files={files[:8]}")
        print(f"  expected={expected}")
        rid += 1

    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()


def main() -> int:
    bin_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\projects\neuromesh\target\release\neuromesh.exe"
    print("=== minimal ===")
    run(bin_path, None)
    print("\n=== diagnostic ===")
    run(bin_path, "diagnostic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
