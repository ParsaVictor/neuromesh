#!/usr/bin/env python3
"""Honest agent-session benchmark: resources, tokens, real multi-step tasks."""
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

CHARS_PER_TOKEN = 4.0
PRICE_IN = 3.0  # USD / 1M input tokens (illustrative mid-market)

# Realistic agent turns: start with pointer, then minimal, then skeleton/expand.
AGENT_TURNS = [
    {
        "id": "T1_fix_memory",
        "steps": [
            ("get_context_packet", {"task": "Why did AppData\\Local get a 899MB graph and how do we refuse it?", "response_detail": "pointer"}),
            ("get_context_packet", {"task": "load_persisted safety check and max_graph_bytes quarantine", "response_detail": "minimal"}),
            ("neuromesh_get_file_skeleton", {"file_path": "crates/neuromesh-graph/src/graph.rs"}),
        ],
    },
    {
        "id": "T2_add_tool",
        "steps": [
            ("get_context_packet", {"task": "How do I add a new MCP tool neuromesh_list_folds?", "response_detail": "pointer"}),
            ("neuromesh_search_symbols", {"query": "tools_list", "limit": 5}),
            ("neuromesh_get_dependencies", {"query": "McpToolHandler"}),
        ],
    },
    {
        "id": "T3_debug_stdin",
        "steps": [
            ("get_context_packet", {"task": "Fix Content-Length hang when client sends garbage on stdin", "response_detail": "pointer"}),
            ("neuromesh_trace", {"query": "read_message", "direction": "out", "depth": 1}),
        ],
    },
    {
        "id": "T4_fa_task",
        "steps": [
            ("get_context_packet", {"task": "پیکربندی چگونه workspace را از IDE env تشخیص می‌دهد؟", "response_detail": "pointer"}),
        ],
    },
    {
        "id": "T5_negative",
        "steps": [
            ("get_context_packet", {"task": "Is there WebSocket live-reload of the code graph?", "response_detail": "minimal"}),
        ],
    },
]


def rss_mb(pid):
    if ctypes is None or os.name != "nt":
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
    ps = ctypes.WinDLL("psapi", use_last_error=True)
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    try:
        c = PMC(); c.cb = ctypes.sizeof(c)
        return c.WorkingSetSize / (1024 * 1024) if ps.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb) else None
    finally:
        k32.CloseHandle(h)


def cpu_sec(pid):
    if ctypes is None or os.name != "nt":
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.OpenProcess(0x0400, False, pid) or k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    class FT(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]
    c, e, k, u = FT(), FT(), FT(), FT()
    try:
        if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return None
        def s(ft):
            return ((ft.hi << 32) | ft.lo) / 1e7
        return s(k) + s(u)
    finally:
        k32.CloseHandle(h)


class Client:
    def __init__(self, bin_path, cwd):
        env = os.environ.copy()
        for k in ["WORKSPACE_FOLDER_PATHS", "VSCODE_CWD", "NEUROMESH_WORKSPACE", "PWD", "NEUROMESH_RESPONSE_DETAIL"]:
            env.pop(k, None)
        self.proc = subprocess.Popen(
            [bin_path, "mcp", cwd],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=cwd, env=env, bufsize=0,
        )
        self.q: queue.Queue = queue.Queue()
        self.pending = {}
        self.stderr = []
        self.nid = 1

        def pump(s, lab):
            for raw in iter(s.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if lab == "e":
                    self.stderr.append(line)
                else:
                    self.q.put(line)

        threading.Thread(target=pump, args=(self.proc.stdout, "o"), daemon=True).start()
        threading.Thread(target=pump, args=(self.proc.stderr, "e"), daemon=True).start()

    def send(self, o):
        assert self.proc.stdin
        self.proc.stdin.write((json.dumps(o, separators=(",", ":")) + "\n").encode())
        self.proc.stdin.flush()

    def wait(self, rid, t=40):
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

    def rpc(self, method, params=None, t=40):
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
            "clientInfo": {"name": "honest-agent-bench", "version": "1"},
            "rootUri": "file:///C:/projects/neuromesh",
            "workspaceFolders": [{"uri": "file:///C:/projects/neuromesh", "name": "neuromesh"}],
        })
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tool(self, name, args, t=40):
        t0 = time.perf_counter()
        resp = self.rpc("tools/call", {"name": name, "arguments": args}, t=t)
        ms = (time.perf_counter() - t0) * 1000
        if not resp:
            return None, ms, "timeout"
        if resp.get("error"):
            return None, ms, str(resp["error"])[:120]
        r = resp.get("result", {})
        if r.get("isError"):
            return None, ms, (r.get("content") or [{}])[0].get("text", "")[:120]
        text = (r.get("content") or [{}])[0].get("text", "")
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


def packet_cost(data: dict) -> tuple[int, int, list[str]]:
    """Return (agent_bytes, selected_proxy_tokens, paths)."""
    raw = json.dumps(data)
    src = data.get("evidence_packet") or data
    files = src.get("files") or data.get("files") or []
    paths = []
    code_chars = 0
    for f in files:
        if isinstance(f, dict):
            paths.append(f.get("path") or "")
            code_chars += len(str(f.get("code") or f.get("skeleton") or f.get("excerpt") or ""))
    tokens_field = data.get("tokens") or src.get("tokens") or {}
    selected = tokens_field.get("selected") or int(code_chars / CHARS_PER_TOKEN) or int(len(raw) / CHARS_PER_TOKEN)
    return len(raw), int(selected), paths


def main() -> int:
    bin_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yoose\.cargo\bin\neuromesh.exe"
    project = r"C:\projects\neuromesh"
    print("=" * 72)
    print("HONEST agent-session benchmark (NeuroMesh MCP)")
    print("=" * 72)

    # Warm index
    t0 = time.perf_counter()
    subprocess.run([bin_path, "index"], cwd=project, capture_output=True, text=True, timeout=180)
    print(f"warm index: {time.perf_counter()-t0:.2f}s")

    c = Client(bin_path, project)
    c.init()
    pid = c.proc.pid
    cpu0 = cpu_sec(pid)
    rss0 = rss_mb(pid)
    print(f"pid={pid} rss0={rss0:.1f}MB cpu0={cpu0}" if rss0 else f"pid={pid}")

    all_ms = []
    agent_bytes = 0
    selected_tokens = 0
    errors = []
    useful_turns = 0
    honest_neg = 0
    turn_summaries = []

    print("\n--- Agent session (pointer-first then expand) ---")
    for turn in AGENT_TURNS:
        print(f"\n[{turn['id']}]")
        turn_paths = []
        turn_hit = False
        for name, args in turn["steps"]:
            data, ms, err = c.tool(name, args)
            all_ms.append(ms)
            r = rss_mb(pid)
            if err or data is None:
                errors.append(f"{turn['id']}:{name}:{err}")
                print(f"  {name}: FAIL {err}")
                continue
            if name == "get_context_packet":
                ab, sel, paths = packet_cost(data)
                agent_bytes += ab
                selected_tokens += sel
                turn_paths.extend(paths)
                claim = data.get("coverage")
                conf = data.get("confidence")
                tier = data.get("resolution_tier")
                hint = data.get("agent_hint")
                print(f"  pointer/minimal {ms:.0f}ms bytes={ab} files={len(paths)} claim={claim} conf={conf} tier={tier}")
                if hint:
                    print(f"    hint: {hint[:100]}")
                if tier == "no_confident_match" or (conf is not None and conf < 0.5 and not paths):
                    honest_neg += 1
                    turn_hit = True
                elif paths:
                    turn_hit = True
            else:
                keys = list(data.keys())[:6]
                print(f"  {name} {ms:.0f}ms keys={keys}")
                turn_hit = True
        if turn_hit:
            useful_turns += 1
        turn_summaries.append((turn["id"], turn_hit, turn_paths[:3]))

    # expand_fold if any fold in last skeleton
    data, ms, err = c.tool("neuromesh_get_file_skeleton", {"file_path": "crates/neuromesh-mcp/src/stdio.rs"})
    if data and not err:
        folds = data.get("folds") or []
        if folds:
            f0 = folds[0] if isinstance(folds[0], dict) else {}
            fid = f0.get("fold_id") or (folds[0] if isinstance(folds[0], str) else None)
            if fid:
                exp, ems, eerr = c.tool("neuromesh_expand_fold", {"fold_id": fid})
                all_ms.append(ems)
                print(f"\n[expand_fold] {ems:.0f}ms err={eerr} body≈{len(json.dumps(exp or {}))}")

    # Burst latency
    print("\n--- Burst latency (pointer × 12) ---")
    burst = []
    for i in range(12):
        _, ms, err = c.tool("get_context_packet", {
            "task": f"How does IndexLock prevent concurrent reindex? #{i}",
            "response_detail": "pointer",
        })
        if not err:
            burst.append(ms)
            rss_mb(pid)
    burst.sort()
    print(f"n={len(burst)} p50={statistics.median(burst):.0f} p95={burst[int(len(burst)*0.95)-1]:.0f} min={burst[0]:.0f} max={burst[-1]:.0f}")

    rss_end = rss_mb(pid)
    cpu1 = cpu_sec(pid)
    cpu_used = (cpu1 - cpu0) if (cpu0 is not None and cpu1 is not None) else None
    print(f"\n--- Resources ---")
    print(f"RSS start={rss0:.1f} end={rss_end:.1f} peak≈{max(x for x in [rss0, rss_end] if x):.1f}MB")
    if cpu_used is not None:
        print(f"CPU during session: {cpu_used:.2f}s")
    c.close()

    # Naive baseline: read the top pointer files fully
    print("\n--- Naive Read baseline (same first-turn files) ---")
    naive_chars = 0
    naive_files = 0
    sample_paths = []
    for tid, hit, paths in turn_summaries[:3]:
        sample_paths.extend(paths)
    sample_paths = list(dict.fromkeys(sample_paths))[:6]
    for p in sample_paths:
        fp = Path(project) / p
        if fp.exists():
            naive_chars += fp.stat().st_size
            naive_files += 1
    naive_tokens = int(naive_chars / CHARS_PER_TOKEN)
    agent_tokens = int(agent_bytes / CHARS_PER_TOKEN)
    print(f"agent session bytes (all packets): {agent_bytes} ≈ {agent_tokens} tokens")
    print(f"naive full-file Read of {naive_files} sample files: {naive_chars} bytes ≈ {naive_tokens} tokens")
    if naive_tokens > 0:
        print(f"token ratio naive/agent for those files: {naive_tokens / max(1, agent_tokens):.1f}x")
    print(f"cost @ ${PRICE_IN}/1M: agent session ${agent_tokens/1e6*PRICE_IN:.4f}  naive sample ${naive_tokens/1e6*PRICE_IN:.4f}")

    print("\n--- Official telemetry ---")
    u = subprocess.run([bin_path, "usage"], cwd=project, capture_output=True, text=True, timeout=30)
    for line in ((u.stdout or "") + (u.stderr or "")).splitlines():
        if any(k in line.lower() for k in ("mean", "reduction", "requests", "tokens", "latency", "summary")):
            print(" ", line.strip())

    print("\n" + "=" * 72)
    print("AGENT VERDICT")
    print("=" * 72)
    print(f"turns useful: {useful_turns}/{len(AGENT_TURNS)}  errors: {len(errors)}")
    print(f"latency p50/p95: {statistics.median(all_ms):.0f}/{sorted(all_ms)[int(len(all_ms)*0.95)-1]:.0f} ms")
    print(f"burst p50: {statistics.median(burst):.0f} ms")
    print(f"RSS peak session: {rss_end:.0f} MB  CPU: {cpu_used if cpu_used is not None else '?'}s")
    print(f"packet tokens session: {agent_tokens}  selected-proxy: {selected_tokens}")
    if errors:
        print("errors:", errors[:5])
    print("=" * 72)
    return 0 if not errors and useful_turns >= 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
