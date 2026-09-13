#!/usr/bin/env python3
"""Multi-protocol / multi-SDK MCP compatibility battery."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time


class Client:
    def __init__(self, bin_path: str, args: list[str] | None = None, cwd: str | None = None):
        env = os.environ.copy()
        for k in [
            "WORKSPACE_FOLDER_PATHS",
            "VSCODE_CWD",
            "CURSOR_WORKSPACE",
            "CURSOR_PROJECT_DIR",
            "NEUROMESH_WORKSPACE",
            "CLAUDE_PROJECT_DIR",
            "PWD",
        ]:
            env.pop(k, None)
        cmd = [bin_path, *(args or ["mcp", r"C:\projects\neuromesh"])]
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd or r"C:\projects\neuromesh",
            env=env,
            bufsize=0,
        )
        self.q: queue.Queue = queue.Queue()
        self.pending: dict[int, dict] = {}
        self.stderr: list[str] = []
        threading.Thread(target=self._pump, args=(self.proc.stdout, "o"), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc.stderr, "e"), daemon=True).start()

    def _pump(self, stream, label: str) -> None:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if label == "e":
                self.stderr.append(line)
            else:
                self.q.put(line)

    def send_raw(self, raw: bytes) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(raw)
        self.proc.stdin.flush()

    def send(self, obj: dict) -> None:
        self.send_raw((json.dumps(obj, separators=(",", ":")) + "\n").encode())

    def wait(self, rid: int, timeout: float = 20.0) -> dict | None:
        end = time.time() + timeout
        while time.time() < end and rid not in self.pending:
            try:
                line = self.q.get(timeout=0.15)
            except queue.Empty:
                if self.proc.poll() is not None:
                    return None
                continue
            if not line or not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = msg.get("id")
            if isinstance(mid, int):
                self.pending[mid] = msg
            elif mid is None and "method" not in msg:
                pass
        return self.pending.get(rid)

    def initialize(self, params: dict, timeout: float = 15.0) -> dict | None:
        self.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params})
        return self.wait(1, timeout)

    def close(self) -> None:
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
    bin_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yoose\.cargo\bin\neuromesh.exe"
    fails = 0

    def ok(name: str, detail: str = "") -> None:
        print(f"  PASS  {name}" + (f" — {detail}" if detail else ""), flush=True)

    def bad(name: str, detail: str = "") -> None:
        nonlocal fails
        fails += 1
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""), flush=True)

    print("=" * 72)
    print("Multi-protocol MCP compatibility")
    print("=" * 72)

    # --- protocol versions ---
    print("\n[1] protocolVersion negotiation")
    for ver in ["2024-11-05", "2025-03-26", "2025-06-18", "1.0", ""]:
        c = Client(bin_path)
        try:
            params = {
                "protocolVersion": ver,
                "capabilities": {},
                "clientInfo": {"name": "compat", "version": "1"},
            }
            if not ver:
                params.pop("protocolVersion")
            resp = c.initialize(params)
            if resp is None or "error" in resp:
                bad(f"protocol {ver or '(absent)'}", str(resp))
            else:
                got = resp["result"].get("protocolVersion")
                ok(f"protocol {ver or '(absent)'}", f"echo={got}")
        finally:
            c.close()

    # --- initialize with rootUri / workspaceFolders / rootPath ---
    print("\n[2] workspace handoff shapes")
    shapes = [
        ("rootUri file://", {"rootUri": "file:///C:/projects/neuromesh"}),
        ("workspaceFolders", {"workspaceFolders": [{"uri": "file:///C:/projects/neuromesh", "name": "n"}]}),
        ("rootPath", {"rootPath": r"C:\projects\neuromesh"}),
        ("none (cwd project)", {}),
    ]
    for label, extra in shapes:
        c = Client(bin_path, ["mcp"], cwd=r"C:\projects\neuromesh")
        try:
            params = {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "compat", "version": "1"},
                **extra,
            }
            resp = c.initialize(params)
            if resp is None or "error" in resp:
                bad(label, str(resp)[:120])
                continue
            c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            c.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            tools = c.wait(2)
            if tools and tools.get("result", {}).get("tools"):
                ok(label, f"{len(tools['result']['tools'])} tools")
            else:
                bad(label, "tools/list failed")
        finally:
            c.close()

    # --- Content-Length framing ---
    print("\n[3] Content-Length framing (Cursor/older SDKs)")
    c = Client(bin_path)
    try:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "cl", "version": "1"},
                },
            },
            separators=(",", ":"),
        ).encode()
        frame = b"Content-Length: %d\r\n\r\n" % len(body) + body
        t0 = time.time()
        c.send_raw(frame)
        resp = c.wait(1, 15)
        if resp and "result" in resp:
            ok("Content-Length initialize", f"{(time.time()-t0)*1000:.0f} ms")
        else:
            bad("Content-Length initialize", str(resp)[:120])
    finally:
        c.close()

    # --- JSON-RPC batch ---
    print("\n[4] JSON-RPC batch array")
    c = Client(bin_path)
    try:
        c.initialize(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "batch", "version": "1"},
            }
        )
        batch = [
            {"jsonrpc": "2.0", "id": 10, "method": "tools/list"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "neuromesh_get_stats", "arguments": {}},
            },
        ]
        c.send_raw((json.dumps(batch) + "\n").encode())
        a = c.wait(10)
        b = c.wait(11)
        if a and b and "result" in a and "result" in b:
            ok("batch tools/list + get_stats")
        else:
            bad("batch", f"10={bool(a)} 11={bool(b)}")
    finally:
        c.close()

    # --- ping / logging / cancel ---
    print("\n[5] ping, logging/setLevel, notifications/cancelled")
    c = Client(bin_path)
    try:
        c.initialize(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "aux", "version": "1"},
            }
        )
        c.send({"jsonrpc": "2.0", "id": 20, "method": "ping"})
        c.send({"jsonrpc": "2.0", "id": 21, "method": "logging/setLevel", "params": {"level": "info"}})
        c.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 99}})
        p = c.wait(20)
        l = c.wait(21)
        if p and "result" in p:
            ok("ping")
        else:
            bad("ping", str(p)[:80])
        if l and "result" in l:
            ok("logging/setLevel")
        else:
            bad("logging/setLevel", str(l)[:80])
        # server must still answer after cancelled notification
        c.send({"jsonrpc": "2.0", "id": 22, "method": "tools/list"})
        t = c.wait(22)
        if t and "result" in t:
            ok("serves after cancelled notification")
        else:
            bad("after cancelled")
    finally:
        c.close()

    # --- tool arg shapes used by different SDKs ---
    print("\n[6] tools/call argument shapes")
    c = Client(bin_path)
    try:
        c.initialize(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "args", "version": "1"},
            }
        )
        shapes = [
            ("arguments object", {"name": "get_context_packet", "arguments": {"prompt": "Where is run_stdio?"}}),
            ("args alias", {"name": "get_context_packet", "args": {"prompt": "Where is run_stdio?"}}),
            ("input alias", {"name": "get_context_packet", "input": {"prompt": "Where is run_stdio?"}}),
            ("short name search", {"name": "search", "arguments": {"query": "load_persisted"}}),
            ("neuromesh_ prefix", {"name": "neuromesh_search_symbols", "arguments": {"query": "load_persisted"}}),
            ("string arguments", {"name": "get_context_packet", "arguments": "{\"prompt\":\"Where is run_stdio?\"}"}),
        ]
        rid = 30
        for label, params in shapes:
            c.send({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": params})
            resp = c.wait(rid, 30)
            if resp is None:
                bad(label, "timeout")
            elif resp.get("error"):
                bad(label, str(resp["error"])[:100])
            elif resp.get("result", {}).get("isError"):
                text = resp["result"].get("content", [{}])[0].get("text", "")
                # empty prompt is expected error for some; not for these
                bad(label, text[:100])
            else:
                ok(label)
            rid += 1
    finally:
        c.close()

    # --- empty prompt must be tool error, not crash ---
    print("\n[7] empty prompt + unknown tool + unknown method")
    c = Client(bin_path)
    try:
        c.initialize(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "err", "version": "1"},
            }
        )
        c.send({"jsonrpc": "2.0", "id": 40, "method": "tools/call", "params": {"name": "get_context_packet", "arguments": {}}})
        e = c.wait(40)
        if e and e.get("result", {}).get("isError"):
            ok("empty prompt → tool error")
        elif e and e.get("error"):
            ok("empty prompt → rpc error (acceptable)")
        else:
            bad("empty prompt", str(e)[:100])

        c.send({"jsonrpc": "2.0", "id": 41, "method": "tools/call", "params": {"name": "not_a_tool", "arguments": {}}})
        u = c.wait(41)
        # unknown tool should not panic the loop
        c.send({"jsonrpc": "2.0", "id": 42, "method": "no/such/method"})
        m = c.wait(42)
        c.send({"jsonrpc": "2.0", "id": 43, "method": "tools/list"})
        still = c.wait(43)
        if still and "result" in still:
            ok("loop alive after unknown tool/method", f"unknown_tool={bool(u)} unknown_method={bool(m)}")
        else:
            bad("loop died after errors")
    finally:
        c.close()

    # --- three concurrent clients ---
    print("\n[8] three concurrent IDE clients")
    clients = []
    try:
        for i in range(3):
            cl = Client(bin_path)
            cl.initialize(
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": f"ide{i}", "version": "1"},
                }
            )
            cl.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            clients.append(cl)
        lat = []
        for i, cl in enumerate(clients):
            cl.send(
                {
                    "jsonrpc": "2.0",
                    "id": 50,
                    "method": "tools/call",
                    "params": {
                        "name": "get_context_packet",
                        "arguments": {"prompt": "Explain index lock and spawn_live_sync", "response_detail": "pointer"},
                    },
                }
            )
            t0 = time.time()
            resp = cl.wait(50, 25)
            ms = (time.time() - t0) * 1000
            if resp and "result" in resp:
                text = resp["result"]["content"][0]["text"]
                data = json.loads(text)
                ok(f"client {i+1} pointer", f"{ms:.0f}ms files={len(data.get('files') or [])}")
                lat.append(ms)
            else:
                bad(f"client {i+1}", str(resp)[:80])
        if lat:
            ok("3-client max latency", f"{max(lat):.0f} ms")
    finally:
        for cl in clients:
            cl.close()

    # --- resources / prompts / completion ---
    print("\n[9] resources, prompts, completion surfaces")
    c = Client(bin_path)
    try:
        c.initialize(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "surf", "version": "1"},
            }
        )
        for rid, method in [
            (60, "resources/list"),
            (61, "resources/templates/list"),
            (62, "prompts/list"),
            (63, "completion/complete"),
        ]:
            params = {}
            if method == "completion/complete":
                params = {"ref": {"type": "ref/prompt", "name": "activate_context"}, "argument": {"name": "task", "value": "x"}}
            c.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            resp = c.wait(rid)
            if resp and ("result" in resp or "error" in resp):
                ok(method, "result" if "result" in resp else f"error {resp['error'].get('code')}")
            else:
                bad(method)
    finally:
        c.close()

    print("\n" + "=" * 72)
    print(f"RESULT: {'PASS' if fails == 0 else f'{fails} FAILURES'}")
    print("=" * 72)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
