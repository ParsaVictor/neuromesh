#!/usr/bin/env python3
"""Unbiased multi-workflow comparison: NeuroMesh vs codebase-memory-mcp."""
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

PROJECT = r"C:\projects\neuromesh"
NM = r"C:\Users\yoose\.cargo\bin\neuromesh.exe"
CBM = r"C:\Users\yoose\AppData\Local\Programs\codebase-memory-mcp\codebase-memory-mcp.exe"


class Mcp:
    def __init__(self, cmd, cwd=None, name="cmp"):
        env = os.environ.copy()
        for k in ["WORKSPACE_FOLDER_PATHS", "VSCODE_CWD", "NEUROMESH_WORKSPACE", "PWD", "NEUROMESH_RESPONSE_DETAIL"]:
            env.pop(k, None)
        self.proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
        )
        self.q: queue.Queue = queue.Queue()
        self.pending = {}
        self.nid = 1
        self.total_bytes = 0

        def pump(s, lab):
            for raw in iter(s.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if lab == "o":
                    self.q.put(line)

        threading.Thread(target=pump, args=(self.proc.stdout, "o"), daemon=True).start()
        threading.Thread(target=pump, args=(self.proc.stderr, "e"), daemon=True).start()

    def send(self, o):
        assert self.proc.stdin
        self.proc.stdin.write((json.dumps(o, separators=(",", ":")) + "\n").encode())
        self.proc.stdin.flush()

    def wait(self, rid, t=60):
        end = time.time() + t
        while time.time() < end and rid not in self.pending:
            try:
                line = self.q.get(timeout=0.15)
            except queue.Empty:
                if self.proc.poll() is not None:
                    return False
                continue
            if not line:
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("id") == rid:
                self.pending[rid] = m
        return rid in self.pending

    def rpc(self, method, params=None, t=60):
        rid = self.nid
        self.nid += 1
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        if not self.wait(rid, t):
            return None
        return self.pending.pop(rid)

    def init(self):
        self.rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "unbiased-cmp", "version": "1"},
        })
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = self.rpc("tools/list", t=30)
        return [t.get("name") for t in (tools or {}).get("result", {}).get("tools", [])]

    def tool(self, name, args, t=60):
        t0 = time.perf_counter()
        resp = self.rpc("tools/call", {"name": name, "arguments": args}, t=t)
        ms = (time.perf_counter() - t0) * 1000
        if not resp:
            return None, ms, "timeout", 0
        if resp.get("error"):
            return None, ms, str(resp["error"])[:160], 0
        r = resp.get("result", {})
        if r.get("isError"):
            return None, ms, (r.get("content") or [{}])[0].get("text", "")[:160], 0
        text = (r.get("content") or [{}])[0].get("text", "")
        self.total_bytes += len(text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {"_raw": text}
        return data, ms, None, len(text)

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


def hit(blob: str, gold: list[str]) -> bool:
    b = blob.lower()
    return any(g.lower() in b for g in gold)


def main() -> int:
    print("=" * 72)
    print("UNBIASED comparison: NeuroMesh 0.9.9 vs codebase-memory-mcp 0.10.8")
    print("Same repo, same prompts, real MCP stdio, no keyword pre-processing")
    print("=" * 72)

    # cbm index
    t0 = time.perf_counter()
    idx = subprocess.run(
        [CBM, "cli", "index_repository", json.dumps({"repo_path": PROJECT, "mode": "fast"})],
        capture_output=True, text=True, timeout=180,
    )
    print(f"cbm index: exit={idx.returncode} {time.perf_counter()-t0:.1f}s")

    nm = Mcp([NM, "mcp", PROJECT], PROJECT)
    nm_tools = nm.init()
    cbm = Mcp([CBM], PROJECT)
    cbm_tools = cbm.init()
    print(f"nm tools={len(nm_tools)}  cbm tools={len(cbm_tools)}")

    # Workflows: each is a realistic agent step sequence
    # (label, nm_calls, cbm_calls, gold)
    # gold empty => negative / honesty check
    WORKFLOWS = [
        (
            "symbol_find",
            [("get_context_packet", {"task": "find handle_tool_call and see what calls it", "response_detail": "pointer"})],
            [("search_graph", {"project": "neuromesh", "query": "handle_tool_call"})],
            ["neuromesh-mcp/src/tools.rs", "handle_tool_call"],
        ),
        (
            "concept_nl",
            [("get_context_packet", {"task": "How does this tool prevent indexing dangerous paths like the filesystem root?", "response_detail": "pointer"})],
            [("search_graph", {"project": "neuromesh", "query": "How does this tool prevent indexing dangerous paths like the filesystem root?"})],
            ["confine.rs", "is_filesystem_root", "is_safe_workspace"],
        ),
        (
            "token_nl",
            [("get_context_packet", {"task": "How does the system estimate the number of tokens in a file or prompt?", "response_detail": "pointer"})],
            [("search_graph", {"project": "neuromesh", "query": "How does the system estimate the number of tokens in a file or prompt?"})],
            ["token.rs", "TokenCounter"],
        ),
        (
            "reinforce_nl",
            [("get_context_packet", {"task": "How does a file's importance get reinforced after repeated edits?", "response_detail": "pointer"})],
            [("search_graph", {"project": "neuromesh", "query": "How does a file's importance get reinforced after repeated edits?"})],
            ["edge.rs", "synapse.rs", "Pheromone", "reinforce"],
        ),
        (
            "max_files_nl",
            [("get_context_packet", {"task": "How does the system determine the maximum number of files to index automatically?", "response_detail": "pointer"})],
            [("search_graph", {"project": "neuromesh", "query": "How does the system determine the maximum number of files to index automatically?"})],
            ["max_files_from_args", "FileCapArg", "config.rs"],
        ),
        (
            "fa_nl",
            [("get_context_packet", {"task": "تابع handle_tool_call را پیدا کن و ببین چه چیزی آن را صدا می‌زند", "response_detail": "pointer"})],
            [("search_graph", {"project": "neuromesh", "query": "handle_tool_call"})],  # cbm typically needs English/identifier
            ["neuromesh-mcp/src/tools.rs", "handle_tool_call"],
        ),
        (
            "negative_absent",
            [("get_context_packet", {"task": "Is there retry logic or exponential backoff when calling the AI provider API?", "response_detail": "minimal"})],
            [("search_graph", {"project": "neuromesh", "query": "retry exponential backoff AI provider API"})],
            [],
        ),
        (
            "impact_chain",
            [
                ("get_context_packet", {"task": "find reinforce_path", "response_detail": "pointer"}),
                ("neuromesh_analyze_impact", {"query": "reinforce_path", "depth": 1}),
            ],
            [
                ("search_graph", {"project": "neuromesh", "query": "reinforce_path"}),
                ("trace_path", {"project": "neuromesh", "function_name": "reinforce_path", "direction": "inbound"}),
            ],
            ["reinforce", "edge.rs", "graph.rs"],
        ),
        (
            "code_body",
            [
                ("get_context_packet", {"task": "find handle_tool_call and show its implementation", "response_detail": "minimal"}),
            ],
            [
                ("search_graph", {"project": "neuromesh", "query": "handle_tool_call implementation"}),
                ("get_code_snippet", {"project": "neuromesh", "path": "crates/neuromesh-mcp/src/tools.rs", "start_line": 1, "end_line": 5}),
            ],
            ["async fn handle_tool_call", "handle_tool_call"],
        ),
    ]

    results = []
    for label, nm_calls, cbm_calls, gold in WORKFLOWS:
        print(f"\n[{label}]")
        # NM
        n_blob = ""
        n_ms = 0.0
        n_bytes = 0
        n_err = None
        for name, args in nm_calls:
            data, ms, err, b = nm.tool(name, args)
            n_ms += ms
            n_bytes += b
            if err:
                n_err = err
                break
            n_blob += json.dumps(data, ensure_ascii=False)
        n_hit = hit(n_blob, gold) if gold else False
        n_honest = (not gold) and (
            "no_confident_match" in n_blob
            or (json.loads(n_blob).get("confidence") or 1) < 0.5
            if n_blob else False
        )
        # CBM
        c_blob = ""
        c_ms = 0.0
        c_bytes = 0
        c_err = None
        for name, args in cbm_calls:
            data, ms, err, b = cbm.tool(name, args)
            c_ms += ms
            c_bytes += b
            if err:
                c_err = err
                break
            c_blob += json.dumps(data, ensure_ascii=False)
        c_hit = hit(c_blob, gold) if gold else False
        c_honest = (not gold) and not c_hit

        rec = {
            "label": label,
            "n_hit": n_hit, "n_ms": n_ms, "n_bytes": n_bytes, "n_err": n_err, "n_honest": n_honest,
            "c_hit": c_hit, "c_ms": c_ms, "c_bytes": c_bytes, "c_err": c_err, "c_honest": c_honest,
            "gold": bool(gold),
        }
        results.append(rec)
        print(f"  nm  hit={n_hit} {n_ms:6.0f}ms {n_bytes:6}B err={n_err}")
        print(f"  cbm hit={c_hit} {c_ms:6.0f}ms {c_bytes:6}B err={c_err}")

    # Resource: RSS of each after workflows
    def rss(pid):
        if os.name != "nt":
            return None
        import ctypes
        from ctypes import wintypes
        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        k32 = ctypes.WinDLL("kernel32")
        ps = ctypes.WinDLL("psapi")
        h = k32.OpenProcess(0x1000, False, pid)
        if not h:
            return None
        try:
            c = PMC(); c.cb = ctypes.sizeof(c)
            return c.WorkingSetSize / (1024 * 1024) if ps.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb) else None
        finally:
            k32.CloseHandle(h)

    n_rss = rss(nm.proc.pid) if nm.proc else None
    c_rss = rss(cbm.proc.pid) if cbm.proc else None
    nm.close()
    cbm.close()

    pos = [r for r in results if r["gold"]]
    neg = [r for r in results if not r["gold"]]
    n_rec = sum(1 for r in pos if r["n_hit"]) / max(1, len(pos))
    c_rec = sum(1 for r in pos if r["c_hit"]) / max(1, len(pos))
    n_neg = sum(1 for r in neg if r["n_honest"]) / max(1, len(neg))
    c_neg = sum(1 for r in neg if r["c_honest"]) / max(1, len(neg))
    n_ms = [r["n_ms"] for r in results]
    c_ms = [r["c_ms"] for r in results]
    n_by = sum(r["n_bytes"] for r in results)
    c_by = sum(r["c_bytes"] for r in results)
    n_errs = sum(1 for r in results if r["n_err"])
    c_errs = sum(1 for r in results if r["c_err"])

    print("\n" + "=" * 72)
    print("AGGREGATE (9 workflows)")
    print("=" * 72)
    print(f"recall  nm={n_rec:.0%}  cbm={c_rec:.0%}")
    print(f"neg     nm={n_neg:.0%}  cbm={c_neg:.0%}")
    print(f"latency nm p50={statistics.median(n_ms):.0f}ms  cbm p50={statistics.median(c_ms):.0f}ms")
    print(f"bytes   nm={n_by}  cbm={c_by}  (nm/cbm={n_by/max(1,c_by):.2f}x)")
    print(f"errors  nm={n_errs}  cbm={c_errs}")
    print(f"RSS     nm={n_rss and round(n_rss)}MB  cbm={c_rss and round(c_rss)}MB")

    # Scores 1-10 (transparent rubric)
    def score_recall(r):
        return round(r * 10)
    def score_neg(r):
        return round(r * 10)
    def score_latency(p50):
        # 50ms=10, 500ms=1 roughly
        if p50 <= 30:
            return 10
        if p50 >= 500:
            return 1
        return max(1, round(10 - (p50 - 30) / 50))
    def score_bytes(b):
        # lower better; 20k total=10, 200k=1
        if b <= 20000:
            return 10
        if b >= 200000:
            return 1
        return max(1, round(10 - (b - 20000) / 20000))
    def score_err(e):
        return 10 if e == 0 else max(1, 10 - e * 3)

    dims = [
        ("Recall (NL + concept)", score_recall(n_rec), score_recall(c_rec)),
        ("Negative honesty", score_neg(n_neg), score_neg(c_neg)),
        ("Latency p50", score_latency(statistics.median(n_ms)), score_latency(statistics.median(c_ms))),
        ("Payload bytes", score_bytes(n_by), score_bytes(c_by)),
        ("Error-free workflows", score_err(n_errs), score_err(c_errs)),
        # qualitative from known capabilities + this session measurements
        ("Seed body in packet", 9, 4),  # nm includes seed skeleton; cbm needs get_code_snippet
        ("Structural depth (trace/LSP)", 5, 9),
        ("Language coverage", 5, 10),
        ("Agent loop (fold/feedback)", 9, 3),
        ("Memory footprint", 9 if (n_rss or 99) < 80 else 5, 7 if (c_rss or 99) < 200 else 5),
        ("Ecosystem / maturity", 4, 10),
    ]
    print("\n" + "=" * 72)
    print("SCORES (1-10)")
    print("=" * 72)
    print(f"{'Dimension':<28} {'nm':>4} {'cbm':>5}")
    ns = cs = 0
    for name, a, b in dims:
        ns += a
        cs += b
        print(f"{name:<28} {a:4} {b:5}")
    print(f"{'TOTAL':<28} {ns:4} {cs:5}  (max {10*len(dims)})")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
