#!/usr/bin/env python3
"""Compare pointer vs minimal get_context_packet over MCP."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time


def call_packet(bin_path: str, detail: str | None) -> None:
    env = os.environ.copy()
    for k in [
        "WORKSPACE_FOLDER_PATHS",
        "VSCODE_CWD",
        "NEUROMESH_WORKSPACE",
        "PWD",
        "CLAUDE_PROJECT_DIR",
    ]:
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

    def pump(stream, label: str) -> None:
        for raw in iter(stream.readline, b""):
            q.put((label, raw.decode("utf-8", "replace").rstrip()))

    threading.Thread(target=pump, args=(proc.stdout, "o"), daemon=True).start()
    threading.Thread(target=pump, args=(proc.stderr, "e"), daemon=True).start()

    def send(obj: dict) -> None:
        assert proc.stdin
        proc.stdin.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        proc.stdin.flush()

    def wait(req_id: int, timeout: float = 40.0) -> bool:
        end = time.time() + timeout
        while time.time() < end and req_id not in pending:
            try:
                lab, line = q.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None:
                    return False
                continue
            if lab != "o" or not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == req_id:
                pending[req_id] = msg
        return req_id in pending

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ptr-test", "version": "1"},
                },
            }
        )
        wait(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        args = {
            "prompt": "How does is_safe_workspace reject AppData Local cache roots?"
        }
        if detail:
            args["response_detail"] = detail
        t0 = time.perf_counter()
        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_context_packet", "arguments": args},
            }
        )
        if not wait(2):
            print(f"detail={detail or 'default'} TIMEOUT")
            return
        ms = (time.perf_counter() - t0) * 1000
        text = pending[2]["result"]["content"][0]["text"]
        data = json.loads(text)
        files = data.get("files") or []
        has_code = any(isinstance(f, dict) and f.get("code") for f in files)
        has_sig = any(isinstance(f, dict) and f.get("signature") for f in files)
        print(
            f"detail={detail or 'default':10} bytes={len(text):5} files={len(files)} "
            f"has_code={has_code} has_signature={has_sig} "
            f"claim={data.get('coverage')} conf={data.get('confidence')} "
            f"tier={data.get('resolution_tier')} {ms:.0f}ms"
        )
        if files:
            f0 = files[0]
            if isinstance(f0, dict):
                keys = sorted(f0.keys())
                print(f"  first keys: {keys}")
                print(f"  path: {f0.get('path')}")
                if f0.get("signature"):
                    print(f"  signature: {str(f0.get('signature'))[:100]}")
    finally:
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
    for detail in (None, "pointer", "minimal"):
        call_packet(bin_path, detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
