#!/usr/bin/env python3
"""End-to-end NeuroMesh MCP stdio handshake probes."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


def run_case(
    name: str,
    bin_path: str,
    cmd_args: list[str],
    cwd: str | None,
    initialize_params: dict | None = None,
    env_extra: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> int:
    env = os.environ.copy()
    for key in [
        "WORKSPACE_FOLDER_PATHS",
        "VSCODE_CWD",
        "CURSOR_WORKSPACE",
        "CURSOR_PROJECT_DIR",
        "NEUROMESH_WORKSPACE",
        "INIT_CWD",
        "JETBRAINS_IDE_PROJECT_PATH",
        "PWD",
        "CLAUDE_PROJECT_DIR",
        "VSCODE_WORKSPACE_FOLDER",
        "GITHUB_WORKSPACE",
    ]:
        env.pop(key, None)
    if env_extra:
        env.update(env_extra)

    print(f"\n=== {name} ===", flush=True)
    cmd = [bin_path, *cmd_args]
    print(f"cmd: {cmd}", flush=True)
    print(f"cwd: {cwd}", flush=True)
    t0 = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    q: queue.Queue = queue.Queue()

    def pump(stream, label: str) -> None:
        for raw in iter(stream.readline, b""):
            q.put((label, raw.decode("utf-8", errors="replace").rstrip("\r\n")))
        q.put((label, None))

    threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True).start()
    threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True).start()

    stderr_lines: list[str] = []
    pending: dict[int, dict] = {}

    def send(obj: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        proc.stdin.flush()

    def wait_id(req_id: int, deadline: float) -> bool:
        while time.time() < deadline and req_id not in pending:
            try:
                label, line = q.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None:
                    return False
                continue
            if label == "err":
                if line:
                    stderr_lines.append(line)
                continue
            if line is None:
                return False
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = msg.get("id")
            if mid in (1, 2, 3):
                pending[mid] = msg
        return req_id in pending

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": initialize_params
                or {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-client-test", "version": "0.0.1"},
                },
            }
        )
        if not wait_id(1, time.time() + timeout):
            print(f"FAIL: no initialize in {time.time()-t0:.2f}s exit={proc.poll()}", flush=True)
            for line in stderr_lines:
                print(f"  | {line}", flush=True)
            return 1
        if "error" in pending[1]:
            print(f"FAIL: initialize error {pending[1]['error']}", flush=True)
            return 1
        info = pending[1]["result"]
        print(
            f"OK initialize {time.time()-t0:.2f}s "
            f"protocol={info.get('protocolVersion')} "
            f"v={info.get('serverInfo', {}).get('version')}",
            flush=True,
        )

        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "neuromesh_get_stats", "arguments": {}},
            }
        )
        if not wait_id(2, time.time() + timeout):
            print("FAIL: tools/list timeout", flush=True)
            return 1
        names = [t.get("name") for t in pending[2].get("result", {}).get("tools", [])]
        print(f"OK tools/list count={len(names)}", flush=True)
        if not wait_id(3, time.time() + timeout):
            print("FAIL: get_stats timeout", flush=True)
            return 1
        if pending[3].get("error"):
            print(f"FAIL: get_stats {pending[3]['error']}", flush=True)
            return 1
        text = pending[3].get("result", {}).get("content", [{}])[0].get("text", "")[:240]
        print(f"OK get_stats: {text}", flush=True)
        for line in stderr_lines:
            print(f"  | {line}", flush=True)
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


def main() -> int:
    bin_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else r"C:\projects\neuromesh\target\release\neuromesh.exe"
    )
    project = r"C:\projects\neuromesh"
    appdata = os.environ.get("LOCALAPPDATA") or r"C:\Users\yoose\AppData\Local"
    fails = 0

    fails += run_case("explicit project path", bin_path, ["mcp", project], None)
    fails += run_case("portable mcp, cwd=project", bin_path, ["mcp"], project)
    fails += run_case("portable mcp, cwd=AppData\\Local", bin_path, ["mcp"], appdata)
    fails += run_case(
        "AppData\\Local + initialize rootUri",
        bin_path,
        ["mcp"],
        appdata,
        initialize_params={
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "cursor-like", "version": "1"},
            "rootUri": "file:///C:/projects/neuromesh",
            "workspaceFolders": [{"uri": "file:///C:/projects/neuromesh", "name": "neuromesh"}],
        },
        timeout=30.0,
    )
    fails += run_case(
        "NEUROMESH_WORKSPACE env",
        bin_path,
        ["mcp"],
        appdata,
        env_extra={"NEUROMESH_WORKSPACE": project},
    )
    fails += run_case(
        "protocol 2025-03-26",
        bin_path,
        ["mcp", project],
        None,
        initialize_params={
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "cursor-like", "version": "1"},
        },
    )
    fails += run_case(
        "Content-Length framed initialize",
        bin_path,
        ["mcp", project],
        None,
    )

    print(f"\n==== RESULT: {'PASS' if fails == 0 else f'{fails} failure(s)'} ====", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
