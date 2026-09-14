#!/usr/bin/env python3
"""Reproduce token_estimate regression and retry coverage claim."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time


def run(bin_path: str) -> None:
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

    def wait(rid, t=35):
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
        "clientInfo": {"name": "reg-repro", "version": "1"},
    }})
    wait(1)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    cases = [
        ("token_estimate", "token_estimate"),
        ("TokenCounter", "TokenCounter"),
        ("token counter estimate", "How are tokens estimated or counted?"),
        ("retry", "Is there retry logic or exponential backoff when calling the AI provider API?"),
    ]
    rid = 10
    for name, prompt in cases:
        send({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {
            "name": "get_context_packet",
            "arguments": {"task": prompt, "response_detail": "minimal"},
        }})
        wait(rid)
        data = json.loads(pending.pop(rid)["result"]["content"][0]["text"])
        files = [f.get("path") for f in (data.get("files") or []) if isinstance(f, dict)]
        claim = data.get("coverage")
        ret = data.get("retrieval") or {}
        if isinstance(claim, dict):
            claim = claim.get("claim")
        print(f"\n=== {name} ===")
        print(f"  claim={claim} tier={ret.get('resolution_tier')} conf={ret.get('confidence')}")
        print(f"  files={files}")
        joined = " ".join(files)
        print(f"  has token.rs={('token.rs' in joined)} TokenCounter={('TokenCounter' in json.dumps(data))}")
    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yoose\.cargo\bin\neuromesh.exe")
