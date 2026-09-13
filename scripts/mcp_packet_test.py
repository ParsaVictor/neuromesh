#!/usr/bin/env python3
"""Call get_context_packet over MCP after the index warms."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time


def main() -> int:
    bin_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else r"C:\projects\neuromesh\target\release\neuromesh.exe"
    )
    project = r"C:\projects\neuromesh"
    env = os.environ.copy()
    for key in [
        "WORKSPACE_FOLDER_PATHS",
        "VSCODE_CWD",
        "CURSOR_WORKSPACE",
        "CURSOR_PROJECT_DIR",
        "NEUROMESH_WORKSPACE",
    ]:
        env.pop(key, None)

    proc = subprocess.Popen(
        [bin_path, "mcp", project],
        cwd=project,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    q: queue.Queue = queue.Queue()

    def pump(stream, label: str) -> None:
        for raw in iter(stream.readline, b""):
            q.put((label, raw.decode("utf-8", "replace").rstrip("\r\n")))
        q.put((label, None))

    threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True).start()
    threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True).start()

    pending: dict[int, dict] = {}
    stderr: list[str] = []

    def send(obj: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        proc.stdin.flush()

    def wait_id(req_id: int, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline and req_id not in pending:
            try:
                label, line = q.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None:
                    return False
                continue
            if label == "err":
                if line:
                    stderr.append(line)
                continue
            if line is None:
                return False
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
                    "clientInfo": {"name": "mcp-packet-test", "version": "1"},
                    "rootUri": "file:///C:/projects/neuromesh",
                    "workspaceFolders": [
                        {"uri": "file:///C:/projects/neuromesh", "name": "neuromesh"}
                    ],
                },
            }
        )
        if not wait_id(1, 15):
            print("FAIL initialize")
            return 1
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        # Give the background index a moment on first run.
        time.sleep(8.0)
        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get_context_packet",
                    "arguments": {
                        "prompt": "How does neuromesh handle AppData Local workspace rejection in MCP startup?"
                    },
                },
            }
        )
        if not wait_id(2, 45):
            print("FAIL get_context_packet timeout")
            for line in stderr:
                print(" |", line)
            return 1
        resp = pending[2]
        if resp.get("error"):
            print("FAIL error", resp["error"])
            return 1
        result = resp.get("result", {})
        text = result.get("content", [{}])[0].get("text", "")
        data = {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            print("non-json packet", text[:400])
            return 1
        files = data.get("files") or []
        coverage = data.get("coverage")
        if isinstance(coverage, dict):
            claim = coverage.get("claim")
            paths = [f.get("path") for f in files[:8] if isinstance(f, dict)]
        else:
            claim = coverage
            paths = [f.get("path") if isinstance(f, dict) else f for f in files[:8]]
        print("OK get_context_packet")
        print("  packet_id:", data.get("packet_id"))
        print("  claim:", claim)
        print("  files:", paths)
        print("  tokens:", data.get("tokens"))
        for line in stderr[-12:]:
            print(" |", line)
        return 0
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


if __name__ == "__main__":
    raise SystemExit(main())
