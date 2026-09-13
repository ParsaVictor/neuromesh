#!/usr/bin/env python3
"""Broad NeuroMesh MCP stability suite: multi-IDE handshake shapes, arg aliases,
batch, framing, recovery, concurrent clients."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


class Client:
    def __init__(self, bin_path: str, args: list[str], cwd: str | None = None, env: dict | None = None):
        e = os.environ.copy()
        for k in [
            "WORKSPACE_FOLDER_PATHS", "VSCODE_CWD", "CURSOR_WORKSPACE", "CURSOR_PROJECT_DIR",
            "NEUROMESH_WORKSPACE", "CLAUDE_PROJECT_DIR", "PWD",
        ]:
            e.pop(k, None)
        if env:
            e.update(env)
        self.proc = subprocess.Popen(
            [bin_path, *args],
            cwd=cwd,
            env=e,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.q: queue.Queue = queue.Queue()
        self.pending: dict = {}
        self.stderr: list[str] = []
        self.nid = 1

        def pump(s, lab):
            for raw in iter(s.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if lab == "e":
                    self.stderr.append(line)
                else:
                    self.q.put(line)

        threading.Thread(target=pump, args=(self.proc.stdout, "o"), daemon=True).start()
        threading.Thread(target=pump, args=(self.proc.stderr, "e"), daemon=True).start()

    def send_raw(self, data: bytes) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def send(self, obj: dict) -> None:
        self.send_raw((json.dumps(obj, separators=(",", ":")) + "\n").encode())

    def send_content_length(self, obj: dict) -> None:
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_raw(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)

    def wait_id(self, rid, timeout=20.0):
        end = time.time() + timeout
        while time.time() < end and rid not in self.pending:
            try:
                line = self.q.get(timeout=0.15)
            except queue.Empty:
                if self.proc.poll() is not None:
                    return False
                continue
            if not line or not line.strip():
                continue
            # batch response
            if line.startswith("["):
                try:
                    for msg in json.loads(line):
                        if isinstance(msg, dict) and msg.get("id") == rid:
                            self.pending[rid] = msg
                except json.JSONDecodeError:
                    pass
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("id") is not None:
                self.pending[msg["id"]] = msg
        return rid in self.pending

    def rpc(self, method, params=None, timeout=20.0):
        rid = self.nid
        self.nid += 1
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        if not self.wait_id(rid, timeout):
            return None
        return self.pending.pop(rid)

    def initialize(self, params=None):
        p = params or {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "stability-suite", "version": "1"},
        }
        resp = self.rpc("initialize", p)
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return resp

    def close(self):
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


def main() -> int:
    bin_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\projects\neuromesh\target\release\neuromesh.exe"
    project = r"C:\projects\neuromesh"
    appdata = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
    fails = 0
    results: list[tuple[str, bool, str]] = []

    def ok(name, detail=""):
        results.append((name, True, detail))
        print(f"  PASS  {name}" + (f" — {detail}" if detail else ""), flush=True)

    def bad(name, detail=""):
        nonlocal fails
        fails += 1
        results.append((name, False, detail))
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""), flush=True)

    print("=" * 70, flush=True)
    print("NeuroMesh MCP stability / multi-IDE suite", flush=True)
    print("=" * 70, flush=True)

    # A. Multi-IDE initialize shapes
    print("\n[A] IDE initialize shapes", flush=True)
    shapes = {
        "cursor-like": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"roots": {"listChanged": True}, "sampling": {}},
            "clientInfo": {"name": "Cursor", "version": "1.0"},
            "rootUri": "file:///C:/projects/neuromesh",
            "workspaceFolders": [{"uri": "file:///C:/projects/neuromesh", "name": "neuromesh"}],
        },
        "claude-desktop": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "claude-desktop", "version": "0.7"},
        },
        "vscode-copilot": {
            "protocolVersion": "2025-03-26",
            "capabilities": {"elicitation": {}},
            "clientInfo": {"name": "vscode", "version": "1.90"},
            "rootPath": project,
        },
        "codex-like": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "codex", "version": "0.1"},
            "cwd": project,
        },
        "empty-caps": {
            "protocolVersion": "2024-11-05",
            "capabilities": None,
            "clientInfo": {"name": "minimal", "version": "1"},
        },
    }
    for name, params in shapes.items():
        c = Client(bin_path, ["mcp"], project)
        try:
            t0 = time.perf_counter()
            resp = c.initialize(params)
            ms = (time.perf_counter() - t0) * 1000
            if resp is None:
                bad(f"init {name}", "timeout")
                continue
            if resp.get("error"):
                bad(f"init {name}", str(resp["error"])[:120])
                continue
            ver = resp.get("result", {}).get("protocolVersion")
            ok(f"init {name}", f"{ms:.0f}ms protocol={ver}")
        finally:
            c.close()

    # B. Tool arg aliases
    print("\n[B] Tool argument aliases", flush=True)
    c = Client(bin_path, ["mcp", project])
    try:
        c.initialize()
        aliases = [
            ("prompt", {"prompt": "Where is is_safe_workspace?"}),
            ("query", {"query": "Where is is_safe_workspace?"}),
            ("task", {"task": "Where is is_safe_workspace?"}),
            ("task_description", {"task_description": "Where is is_safe_workspace?"}),
            ("string-args-name", {"name": "get_context_packet", "input": {"prompt": "confine workspace"}}),
        ]
        for label, args in aliases:
            rid = c.nid
            c.nid += 1
            c.send({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": "get_context_packet", "arguments": args}})
            if not c.wait_id(rid, 30):
                bad(f"args {label}", "timeout")
                continue
            resp = c.pending.pop(rid)
            if resp.get("error"):
                bad(f"args {label}", str(resp["error"])[:120])
                continue
            text = resp["result"]["content"][0]["text"]
            try:
                data = json.loads(text)
                nfiles = len(data.get("files") or [])
            except Exception:
                nfiles = -1
            ok(f"args {label}", f"files={nfiles}")

        # short tool names
        for tname in ["get_context", "neuromesh_get_context", "search", "stats"]:
            rid = c.nid
            c.nid += 1
            args = {"prompt": "test"} if "context" in tname else {}
            c.send({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": tname, "arguments": args}})
            if not c.wait_id(rid, 25):
                bad(f"alias tool {tname}", "timeout")
                continue
            resp = c.pending.pop(rid)
            if resp.get("error") and "error" in str(resp.get("error", {})).lower():
                # tool_error is still result.isError
                if resp.get("result", {}).get("isError"):
                    bad(f"alias tool {tname}", str(resp["result"]["content"][0]["text"])[:100])
                else:
                    bad(f"alias tool {tname}", str(resp["error"])[:100])
                continue
            ok(f"alias tool {tname}")
    finally:
        c.close()

    # C. Batch JSON-RPC + Content-Length + ping
    print("\n[C] Framing / batch / ping", flush=True)
    c = Client(bin_path, ["mcp", project])
    try:
        c.initialize()
        rid = 100
        batch = [
            {"jsonrpc": "2.0", "id": rid, "method": "ping"},
            {"jsonrpc": "2.0", "id": rid + 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": rid + 2, "method": "resources/list"},
        ]
        c.send_raw((json.dumps(batch) + "\n").encode())
        if c.wait_id(rid, 10) and c.wait_id(rid + 1, 10) and c.wait_id(rid + 2, 10):
            ok("batch array", f"tools={len(c.pending[rid+1]['result']['tools'])}")
        else:
            bad("batch array", f"got ids={list(c.pending.keys())}")
        c.pending.clear()

        # Content-Length framed call
        body = {"jsonrpc": "2.0", "id": 200, "method": "ping"}
        c.send_content_length(body)
        if c.wait_id(200, 10):
            ok("Content-Length ping")
        else:
            bad("Content-Length ping", "timeout")

        resp = c.rpc("logging/setLevel", {"level": "info"})
        if resp and not resp.get("error"):
            ok("logging/setLevel")
        else:
            bad("logging/setLevel", str(resp)[:80] if resp else "timeout")
    finally:
        c.close()

    # D. Panic recovery
    print("\n[D] Panic recovery", flush=True)
    c = Client(bin_path, ["mcp", project])
    try:
        c.initialize()
        # probe only exists in debug tests — use empty tool name instead
        resp = c.rpc("tools/call", {"name": "", "arguments": {}})
        if resp and (resp.get("error") or resp.get("result", {}).get("isError")):
            ok("empty tool name error", "clean tool error")
        else:
            bad("empty tool name", str(resp)[:100])
        resp = c.rpc("ping")
        if resp and not resp.get("error"):
            ok("still serving after error")
        else:
            bad("still serving after error")
    finally:
        c.close()

    # E. AppData refuse + rootUri adopt
    print("\n[E] Unsafe cwd + rootUri adopt", flush=True)
    c = Client(bin_path, ["mcp"], appdata)
    try:
        t0 = time.perf_counter()
        resp = c.initialize(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ide", "version": "1"},
                "rootUri": "file:///C:/projects/neuromesh",
                "workspaceFolders": [{"uri": "file:///C:/projects/neuromesh", "name": "n"}],
            }
        )
        ms = (time.perf_counter() - t0) * 1000
        if resp and not resp.get("error") and ms < 2000:
            ok("AppData+rootUri init", f"{ms:.0f}ms")
        else:
            bad("AppData+rootUri init", f"{ms:.0f}ms {resp}")
        st = c.rpc("tools/call", {"name": "neuromesh_get_stats", "arguments": {}}, timeout=15)
        if st and not st.get("error"):
            ok("tools after AppData start")
        else:
            bad("tools after AppData start")
    finally:
        c.close()

    # F. Concurrent multi-IDE
    print("\n[F] 3 concurrent clients", flush=True)
    clients = []
    try:
        for i in range(3):
            cl = Client(bin_path, ["mcp", project])
            cl.initialize({"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": f"ide{i}", "version": "1"}})
            clients.append(cl)
        for i, cl in enumerate(clients):
            t0 = time.perf_counter()
            resp = cl.rpc("tools/call", {"name": "get_context_packet", "arguments": {"prompt": "explain index lock", "response_detail": "pointer"}}, timeout=30)
            ms = (time.perf_counter() - t0) * 1000
            if resp and not resp.get("error") and not resp.get("result", {}).get("isError"):
                text = resp["result"]["content"][0]["text"]
                data = json.loads(text)
                ok(f"concurrent {i+1}", f"{ms:.0f}ms files={len(data.get('files') or [])}")
            else:
                bad(f"concurrent {i+1}", str(resp)[:120] if resp else "timeout")
    finally:
        for cl in clients:
            cl.close()

    # G. Latency budget
    print("\n[G] Latency budget (pointer)", flush=True)
    c = Client(bin_path, ["mcp", project])
    try:
        c.initialize()
        samples = []
        for i in range(8):
            t0 = time.perf_counter()
            resp = c.rpc(
                "tools/call",
                {
                    "name": "get_context_packet",
                    "arguments": {"prompt": f"How does spawn_live_sync take the index lock? sample {i}", "response_detail": "pointer"},
                },
                timeout=30,
            )
            samples.append((time.perf_counter() - t0) * 1000)
        samples.sort()
        p50 = samples[len(samples) // 2]
        p95 = samples[int(len(samples) * 0.95) - 1] if len(samples) > 1 else samples[-1]
        if p50 < 400:
            ok("pointer p50", f"{p50:.0f}ms (p95={p95:.0f}ms)")
        else:
            bad("pointer p50", f"{p50:.0f}ms too slow")
    finally:
        c.close()

    print("\n" + "=" * 70, flush=True)
    print(f"RESULT: {'PASS' if fails == 0 else f'{fails} FAILURES'} ({sum(1 for _,s,_ in results if s)}/{len(results)})", flush=True)
    for name, success, detail in results:
        if not success:
            print(f"  FAIL  {name}: {detail}", flush=True)
    print("=" * 70, flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
