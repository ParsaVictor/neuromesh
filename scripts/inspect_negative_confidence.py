#!/usr/bin/env python3
"""Inspect retry/backoff negative query fields across response_detail modes."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

PROMPT = "Is there retry logic or exponential backoff when calling the AI provider API?"


def main() -> int:
    bin_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yoose\.cargo\bin\neuromesh.exe"
    env = os.environ.copy()
    for k in ["WORKSPACE_FOLDER_PATHS", "VSCODE_CWD", "NEUROMESH_WORKSPACE", "PWD", "NEUROMESH_RESPONSE_DETAIL"]:
        env.pop(k, None)
    proc = subprocess.Popen(
        [bin_path, "mcp", r"C:\projects\neuromesh"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=r"C:\projects\neuromesh", env=env, bufsize=0,
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

    def send(o):
        assert proc.stdin
        proc.stdin.write((json.dumps(o, separators=(",", ":")) + "\n").encode())
        proc.stdin.flush()

    def wait(rid, t=30):
        end = time.time() + t
        while time.time() < end and rid not in pending:
            try:
                line = q.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None:
                    return False
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("id") == rid:
                pending[rid] = m
        return rid in pending

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "neg-inspect", "version": "1"},
    }})
    wait(1)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    rid = 10
    for detail in (None, "minimal", "pointer", "diagnostic"):
        args = {"task": PROMPT}
        if detail:
            args["response_detail"] = detail
        send({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
              "params": {"name": "get_context_packet", "arguments": args}})
        wait(rid)
        data = json.loads(pending.pop(rid)["result"]["content"][0]["text"])
        src = data.get("evidence_packet") or data
        cov = src.get("coverage") or data.get("coverage")
        ret = src.get("retrieval") or data.get("retrieval") or {}
        claim = cov.get("claim") if isinstance(cov, dict) else cov
        files = [f.get("path") if isinstance(f, dict) else f for f in (src.get("files") or data.get("files") or [])][:4]
        print(f"\n=== detail={detail or 'default'} ===")
        print(f"  coverage.claim      = {claim}")
        print(f"  retrieval.claim     = {ret.get('claim')}")
        print(f"  resolution_tier     = {ret.get('resolution_tier') or data.get('resolution_tier')}")
        print(f"  confidence          = {ret.get('confidence') or data.get('confidence')}")
        print(f"  sufficiency         = {ret.get('sufficiency_score')}")
        print(f"  files               = {files}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
