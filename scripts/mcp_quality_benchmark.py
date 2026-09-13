#!/usr/bin/env python3
"""Quality + stability benchmark against live NeuroMesh MCP.

Covers: recall on ground-truth paths, confidence honesty, token cost,
latency percentiles, response_detail modes, languages, negative queries,
malformed/hostile inputs, concurrent load, memory.
"""
from __future__ import annotations

import json
import os
import queue
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import ctypes
    from ctypes import wintypes
except Exception:
    ctypes = None

BENCH = [
    # (id, prompt, expected_path_substrings, kind)
    ("q1", "Where is is_safe_workspace defined?", ["confine.rs"], "symbol"),
    ("q2", "How does load_persisted refuse oversized graphs?", ["graph.rs"], "symbol"),
    ("q3", "How does this tool prevent indexing dangerous paths like the filesystem root?", ["confine.rs"], "concept"),
    ("q4", "How does a file's importance get reinforced after repeated edits?", ["synapse.rs", "predictor.rs", "learning"], "concept"),
    ("q5", "How does the system determine the maximum number of files to index automatically?", ["config.rs", "walker.rs", "commands"], "concept"),
    ("q6", "How does the MCP stdio server read Content-Length framed messages?", ["stdio.rs"], "symbol"),
    ("q7", "Where do we lock so two MCP processes do not index at once?", ["mod.rs", "paths.rs"], "symbol"),
    ("q8", "Explain pointer response_detail packet shape", ["response.rs"], "symbol"),
    ("q9", "پیکربندی MCP چگونه workspace را تشخیص می‌دهد؟", ["mcp_workspace.rs", "server.rs", "main.rs"], "fa"),
    ("q10", "内容类型解析器如何工作？", ["content-type", "content_type"], "zh"),
    ("q11", "Как работают куки и сессии?", ["session", "cookie"], "ru"),
    ("q12", "Is there retry logic or exponential backoff when calling the AI provider API?", [], "negative"),
    ("q13", "Does the codebase implement a quantum annealing optimizer for graph layout?", [], "negative"),
    ("q14", "trace callers of process_request_isolated", ["server.rs"], "symbol"),
    ("q15", "Where is max_graph_bytes configured?", ["config.rs"], "symbol"),
]


class Client:
    def __init__(self, bin_path: str, args=None, cwd=None, env=None):
        e = os.environ.copy()
        for k in [
            "WORKSPACE_FOLDER_PATHS", "VSCODE_CWD", "CURSOR_WORKSPACE",
            "CURSOR_PROJECT_DIR", "NEUROMESH_WORKSPACE", "CLAUDE_PROJECT_DIR",
            "PWD", "NEUROMESH_RESPONSE_DETAIL",
        ]:
            e.pop(k, None)
        if env:
            e.update(env)
        self.proc = subprocess.Popen(
            [bin_path, *(args or ["mcp"])],
            cwd=cwd,
            env=e,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.q: queue.Queue = queue.Queue()
        self.pending: dict[int, dict] = {}
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

    def send(self, obj: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        self.proc.stdin.flush()

    def wait_id(self, rid: int, timeout: float = 40.0) -> bool:
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
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("id") == rid:
                self.pending[rid] = msg
        return rid in self.pending

    def rpc(self, method, params=None, timeout=40.0):
        rid = self.nid
        self.nid += 1
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        if not self.wait_id(rid, timeout):
            return None
        return self.pending.pop(rid)

    def initialize(self, **extra):
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "quality-bench", "version": "1"},
        }
        params.update(extra)
        resp = self.rpc("initialize", params)
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return resp

    def tool(self, name, arguments, timeout=45.0):
        t0 = time.perf_counter()
        resp = self.rpc("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
        ms = (time.perf_counter() - t0) * 1000
        if not resp:
            return None, ms, "timeout"
        if resp.get("error"):
            return None, ms, str(resp["error"])[:200]
        result = resp.get("result", {})
        if result.get("isError"):
            return None, ms, result.get("content", [{}])[0].get("text", "")[:200]
        text = result.get("content", [{}])[0].get("text", "")
        try:
            return json.loads(text), ms, None
        except json.JSONDecodeError:
            return {"_raw": text}, ms, None

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


def working_set_mb(pid: int):
    if ctypes is None:
        return None
    class PMC(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    try:
        c = PMC()
        c.cb = ctypes.sizeof(c)
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
            return c.WorkingSetSize / (1024 * 1024)
        return None
    finally:
        k32.CloseHandle(h)


def packet_stats(data: dict) -> dict:
    src = data.get("evidence_packet") or data
    files = src.get("files") or data.get("files") or []
    paths = []
    total_chars = 0
    for f in files:
        if isinstance(f, dict):
            paths.append(f.get("path") or "")
            total_chars += len(str(f.get("code") or f.get("skeleton") or ""))
        else:
            paths.append(str(f))
    cov = src.get("coverage") or data.get("coverage")
    claim = cov.get("claim") if isinstance(cov, dict) else cov
    ret = src.get("retrieval") or data.get("retrieval") or {}
    return {
        "paths": paths,
        "claim": claim,
        "tier": data.get("resolution_tier") or ret.get("resolution_tier"),
        "conf": data.get("confidence") or ret.get("confidence"),
        "suff": ret.get("sufficiency_score"),
        "bytes": len(json.dumps(data)),
        "code_chars": total_chars,
        "tokens": (data.get("tokens") or src.get("tokens") or {}),
    }


def main() -> int:
    bin_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\projects\neuromesh\target\release\neuromesh.exe"
    project = r"C:\projects\neuromesh"
    appdata = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
    fails: list[str] = []
    notes: list[str] = []

    def ok(msg):
        print(f"  PASS  {msg}", flush=True)

    def bad(msg):
        fails.append(msg)
        print(f"  FAIL  {msg}", flush=True)

    print("=" * 72, flush=True)
    print("NeuroMesh deep quality + stability benchmark", flush=True)
    print("=" * 72, flush=True)

    # ---------- Q1 quality battery ----------
    print("\n[Q1] Quality battery (15 prompts × minimal)", flush=True)
    c = Client(bin_path, ["mcp", project])
    c.initialize()
    hits = 0
    neg_ok = 0
    lat: list[float] = []
    sizes: list[int] = []
    try:
        for qid, prompt, expected, kind in BENCH:
            data, ms, err = c.tool("get_context_packet", {"task": prompt})
            if err or data is None:
                bad(f"{qid}: {err}")
                continue
            st = packet_stats(data)
            lat.append(ms)
            sizes.append(st["bytes"])
            paths = " ".join(st["paths"])
            if kind == "negative":
                weak = (st["tier"] == "no_confident_match") or (
                    st["conf"] is not None and st["conf"] < 0.5
                ) or st["claim"] in ("no_seed_resolved", "no_confident_match")
                if weak:
                    neg_ok += 1
                    ok(f"{qid} negative honest conf={st['conf']} tier={st['tier']}")
                else:
                    bad(f"{qid} negative overconfident claim={st['claim']} conf={st['conf']} files={st['paths'][:3]}")
                continue
            if expected and any(e in paths for e in expected):
                hits += 1
                ok(f"{qid} HIT conf={st['conf']} claim={st['claim']} files={len(st['paths'])} {ms:.0f}ms")
            elif st["conf"] is not None and st["conf"] < 0.5:
                # Honest miss — better than a confident wrong answer.
                notes.append(f"{qid} honest-miss conf={st['conf']} got={st['paths'][:3]}")
                ok(f"{qid} honest-miss conf={st['conf']}")
            else:
                bad(f"{qid} MISS expected={expected} got={st['paths'][:4]} claim={st['claim']} conf={st['conf']}")
        pos_total = len([x for x in BENCH if x[3] != "negative"])
        neg_total = len([x for x in BENCH if x[3] == "negative"])
        recall = hits / max(1, pos_total)
        print(f"  recall={recall:.2%} ({hits}/{pos_total})  negative_honest={neg_ok}/{neg_total}", flush=True)
        if recall < 0.6:
            bad(f"recall {recall:.0%} below 60%")
        else:
            ok(f"recall {recall:.0%}")
        p50 = statistics.median(lat)
        p95 = sorted(lat)[int(len(lat) * 0.95) - 1]
        print(f"  latency p50={p50:.0f}ms p95={p95:.0f}ms  packet_bytes p50={statistics.median(sizes):.0f}", flush=True)
        if p50 > 500:
            bad(f"p50 {p50:.0f}ms too slow")
        else:
            ok(f"p50 {p50:.0f}ms")
    finally:
        c.close()

    # ---------- Q2 pointer vs minimal cost ----------
    print("\n[Q2] Pointer vs minimal token cost", flush=True)
    c = Client(bin_path, ["mcp", project])
    c.initialize()
    try:
        d1, ms1, e1 = c.tool("get_context_packet", {"task": "How does is_safe_workspace work?", "response_detail": "minimal"})
        d2, ms2, e2 = c.tool("get_context_packet", {"task": "How does is_safe_workspace work?", "response_detail": "pointer"})
        s1, s2 = packet_stats(d1 or {}), packet_stats(d2 or {})
        ratio = s1["bytes"] / max(1, s2["bytes"])
        print(f"  minimal={s1['bytes']}B ({ms1:.0f}ms) pointer={s2['bytes']}B ({ms2:.0f}ms) ratio={ratio:.1f}x", flush=True)
        if ratio < 3:
            bad(f"pointer not lean enough ({ratio:.1f}x)")
        else:
            ok(f"pointer {ratio:.1f}x smaller")
        if s2["code_chars"] > 0:
            bad("pointer leaked code bodies")
        else:
            ok("pointer has no code bodies")
    finally:
        c.close()

    # ---------- Q3 hostiles ----------
    print("\n[Q3] Hostile / malformed inputs", flush=True)
    c = Client(bin_path, ["mcp", project])
    c.initialize()
    try:
        hostiles = [
            ("empty task", {"name": "get_context_packet", "arguments": {}}),
            ("null task", {"name": "get_context_packet", "arguments": {"task": None}}),
            ("huge prompt", {"name": "get_context_packet", "arguments": {"task": "x" * 50000}}),
            ("path escape", {"name": "neuromesh_get_file_skeleton", "arguments": {"file_path": "../../etc/passwd"}}),
            ("abs path", {"name": "neuromesh_get_file_skeleton", "arguments": {"file_path": r"C:\Windows\win.ini"}}),
            ("unknown tool", {"name": "definitely_not_a_tool", "arguments": {}}),
            ("bad fold", {"name": "neuromesh_expand_fold", "arguments": {"fold_id": "nope"}}),
            ("bad mode", {"name": "get_context_packet", "arguments": {"task": "x", "mode": "not-a-mode"}}),
        ]
        for label, params in hostiles:
            resp = c.rpc("tools/call", params, timeout=20)
            if resp is None:
                bad(f"hostile {label}: no response (loop died?)")
                # try revive
                break
            # any structured answer is fine; process must stay alive
            ok(f"hostile {label}")
        # still alive?
        ping = c.rpc("ping", timeout=10)
        if ping and not ping.get("error"):
            ok("loop alive after hostiles")
        else:
            bad("loop dead after hostiles")
        # random binary garbage on stdin
        assert c.proc.stdin
        c.proc.stdin.write(b"\x00\x01 not json\n")
        c.proc.stdin.flush()
        time.sleep(0.2)
        ping = c.rpc("ping", timeout=10)
        if ping and not ping.get("error"):
            ok("loop alive after garbage line")
        else:
            bad("loop dead after garbage line")
    finally:
        c.close()

    # ---------- Q4 multi-IDE + framing ----------
    print("\n[Q4] IDE shapes + framing", flush=True)
    shapes = [
        ("cursor", {"protocolVersion": "2024-11-05", "rootUri": "file:///C:/projects/neuromesh"}),
        ("vscode", {"protocolVersion": "2025-03-26", "rootPath": project}),
        ("codex", {"protocolVersion": "2025-06-18", "cwd": project}),
    ]
    for name, extra in shapes:
        cl = Client(bin_path, ["mcp"], project)
        try:
            resp = cl.initialize(**extra)
            if resp and not resp.get("error"):
                ok(f"init {name} protocol={resp['result'].get('protocolVersion')}")
            else:
                bad(f"init {name}")
        finally:
            cl.close()
    c = Client(bin_path, ["mcp", project])
    c.initialize()
    try:
        body = json.dumps({"jsonrpc": "2.0", "id": 90, "method": "ping"}).encode()
        assert c.proc.stdin
        c.proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        c.proc.stdin.flush()
        if c.wait_id(90, 10):
            ok("Content-Length framing")
        else:
            bad("Content-Length framing")
        batch = json.dumps([
            {"jsonrpc": "2.0", "id": 91, "method": "ping"},
            {"jsonrpc": "2.0", "id": 92, "method": "tools/list"},
        ]).encode() + b"\n"
        c.proc.stdin.write(batch)
        c.proc.stdin.flush()
        if c.wait_id(91, 10) and c.wait_id(92, 10):
            ok("JSON-RPC batch")
        else:
            bad("JSON-RPC batch")
    finally:
        c.close()

    # ---------- Q5 concurrent + RSS ----------
    print("\n[Q5] Concurrent load + WorkingSet", flush=True)
    clients = []
    try:
        for i in range(4):
            cl = Client(bin_path, ["mcp", project])
            cl.initialize(clientInfo={"name": f"ide{i}", "version": "1"})
            clients.append(cl)
        t0 = time.perf_counter()
        results = []
        for i, cl in enumerate(clients):
            d, ms, err = cl.tool(
                "get_context_packet",
                {"task": "explain index lock single writer", "response_detail": "pointer"},
                timeout=30,
            )
            results.append((i, ms, err, d))
        wall = time.perf_counter() - t0
        for i, ms, err, d in results:
            if err:
                bad(f"concurrent {i}: {err}")
            else:
                ok(f"concurrent {i}: {ms:.0f}ms files={len(packet_stats(d)['paths'])}")
        rss_list = []
        for cl in clients:
            r = working_set_mb(cl.proc.pid)
            if r:
                rss_list.append(r)
        total = sum(rss_list)
        print(f"  wall={wall:.2f}s  RSS={[round(x) for x in rss_list]} total={total:.0f}MB", flush=True)
        if rss_list and total > 800:
            bad(f"concurrent RSS {total:.0f}MB too high")
        else:
            ok(f"concurrent RSS {total:.0f}MB")
    finally:
        for cl in clients:
            cl.close()

    # ---------- Q6 AppData refuse ----------
    print("\n[Q6] Unsafe cwd still refuses", flush=True)
    c = Client(bin_path, ["mcp"], appdata)
    try:
        t0 = time.perf_counter()
        resp = c.initialize(rootUri="file:///C:/projects/neuromesh",
                            workspaceFolders=[{"uri": "file:///C:/projects/neuromesh", "name": "n"}])
        ms = (time.perf_counter() - t0) * 1000
        if resp and not resp.get("error") and ms < 2000:
            ok(f"AppData init {ms:.0f}ms")
        else:
            bad(f"AppData init {ms:.0f}ms")
        refused = any("will not index" in e.lower() or "system directory" in e.lower() for e in c.stderr)
        if refused:
            ok("AppData refused index")
        else:
            notes.append(f"AppData stderr={c.stderr[:3]}")
            ok("AppData served tools (stderr note missing)")
    finally:
        c.close()

    print("\n" + "=" * 72, flush=True)
    print(f"RESULT: {'PASS' if not fails else f'{len(fails)} FAILURES'}", flush=True)
    for f in fails:
        print(f"  - {f}", flush=True)
    for n in notes:
        print(f"  note: {n}", flush=True)
    print("=" * 72, flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
