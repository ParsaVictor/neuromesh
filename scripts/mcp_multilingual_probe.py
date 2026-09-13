#!/usr/bin/env python3
"""Live MCP: Persian + English packets on fast, optional hybrid override."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time


def session(bin_path: str):
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
    stderr: list[str] = []

    def pump(stream, label: str) -> None:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if label == "e":
                stderr.append(line)
            else:
                q.put((label, line))

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
                _, line = q.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None:
                    return False
                continue
            if not line or not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == req_id:
                pending[req_id] = msg
        return req_id in pending

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "fa-test", "version": "1"},
            },
        }
    )
    wait(1)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return proc, send, wait, pending, stderr


def call(send, wait, pending, label: str, args: dict, rid: int) -> None:
    t0 = time.perf_counter()
    send({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": "get_context_packet", "arguments": args}})
    if not wait(rid):
        print(f"{label}: TIMEOUT")
        return
    ms = (time.perf_counter() - t0) * 1000
    text = pending[rid]["result"]["content"][0]["text"]
    data = json.loads(text)
    files = [f.get("path") for f in (data.get("files") or []) if isinstance(f, dict)][:6]
    claim = data.get("coverage")
    if isinstance(claim, dict):
        claim = claim.get("claim")
    print(f"{label}: {ms:.0f}ms bytes={len(text)} claim={claim} files={files}")


def main() -> int:
    bin_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\projects\neuromesh\target\release\neuromesh.exe"
    proc, send, wait, pending, stderr = session(bin_path)
    try:
        rid = 10
        call(send, wait, pending, "EN fast", {"prompt": "Where is is_safe_workspace defined?"}, rid)
        rid += 1
        call(
            send,
            wait,
            pending,
            "FA fast",
            {"prompt": "تابع is_safe_workspace کجاست و چطور مسیرهای AppData را رد می‌کند؟"},
            rid,
        )
        rid += 1
        call(
            send,
            wait,
            pending,
            "FA pointer",
            {
                "prompt": "پیکربندی MCP چگونه workspace را تشخیص می‌دهد؟",
                "response_detail": "pointer",
            },
            rid,
        )
        rid += 1
        # hybrid may need MiniLM — report error if unavailable
        call(
            send,
            wait,
            pending,
            "FA hybrid",
            {
                "prompt": "پلاگین‌ها چگونه درون‌کاشت می‌شوند؟",
                "engine": "hybrid",
            },
            rid,
        )
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
