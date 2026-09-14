#!/usr/bin/env python3
"""NeuroMesh MCP effectiveness bench: RAM/CPU, latency, compression, tokens, cost."""
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

# Rough token estimate: ~4 chars/token for mixed EN/code (conservative).
CHARS_PER_TOKEN = 4.0

# Public list prices (USD / 1M tokens) — illustrative, not vendor-official.
# Claude Sonnet-class and GPT-4o-class blended middle of the market 2026.
PRICING = {
    "blended_mid": {"in": 3.00, "out": 15.00},
    "sonnet_like": {"in": 3.00, "out": 15.00},
    "haiku_like": {"in": 0.80, "out": 4.00},
}

PROMPTS = [
    "Where is is_safe_workspace defined?",
    "How does load_persisted refuse oversized graphs?",
    "How does this tool prevent indexing dangerous paths like the filesystem root?",
    "How does a file's importance get reinforced after repeated edits?",
    "How does the system determine the maximum number of files to index automatically?",
    "How does the MCP stdio server read Content-Length framed messages?",
    "Where do we lock so two MCP processes do not index at once?",
    "Explain pointer response_detail packet shape",
    "How does get_context_packet work end to end?",
    "Where is max_graph_bytes configured?",
    "پیکربندی MCP چگونه workspace را تشخیص می‌دهد؟",
    "Как работают куки и сессии?",
]


class ProcMetrics:
    def __init__(self, pid: int):
        self.pid = pid
        self._ok = ctypes is not None and os.name == "nt"
        self.peak_rss = 0.0
        self.samples: list[float] = []
        self.cpu_seconds = 0.0
        if self._ok:
            class PMC(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ]
            self._PMC = PMC
            self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._psapi = ctypes.WinDLL("psapi", use_last_error=True)

    def rss_mb(self) -> float | None:
        if not self._ok:
            return None
        h = self._k32.OpenProcess(0x1000, False, self.pid)
        if not h:
            return None
        try:
            c = self._PMC()
            c.cb = ctypes.sizeof(c)
            if self._psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
                mb = c.WorkingSetSize / (1024 * 1024)
                self.samples.append(mb)
                self.peak_rss = max(self.peak_rss, mb)
                return mb
            return None
        finally:
            self._k32.CloseHandle(h)

    def cpu_seconds_now(self) -> float | None:
        # GetProcessTimes
        if not self._ok:
            return None
        h = self._k32.OpenProcess(0x0400, False, self.pid)  # PROCESS_QUERY_INFORMATION
        if not h:
            h = self._k32.OpenProcess(0x1000, False, self.pid)
        if not h:
            return None
        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]
        creation = FILETIME()
        exit_t = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        try:
            ok = self._k32.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(exit_t),
                                           ctypes.byref(kernel), ctypes.byref(user))
            if not ok:
                return None
            def to_s(ft):
                return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7
            return to_s(kernel) + to_s(user)
        finally:
            self._k32.CloseHandle(h)


class Client:
    def __init__(self, bin_path: str, args=None, cwd=None):
        env = os.environ.copy()
        for k in ["WORKSPACE_FOLDER_PATHS", "VSCODE_CWD", "CURSOR_WORKSPACE",
                  "CURSOR_PROJECT_DIR", "NEUROMESH_WORKSPACE", "CLAUDE_PROJECT_DIR",
                  "PWD", "NEUROMESH_RESPONSE_DETAIL"]:
            env.pop(k, None)
        self.proc = subprocess.Popen(
            [bin_path, *(args or ["mcp"])],
            cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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

    def initialize(self):
        resp = self.rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "perf-bench", "version": "1"},
            "rootUri": "file:///C:/projects/neuromesh",
            "workspaceFolders": [{"uri": "file:///C:/projects/neuromesh", "name": "neuromesh"}],
        })
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return resp

    def tool(self, name, arguments, timeout=45.0):
        t0 = time.perf_counter()
        resp = self.rpc("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
        ms = (time.perf_counter() - t0) * 1000
        if not resp:
            return None, ms, "timeout"
        if resp.get("error"):
            return None, ms, str(resp["error"])[:160]
        result = resp.get("result", {})
        if result.get("isError"):
            return None, ms, (result.get("content") or [{}])[0].get("text", "")[:160]
        text = (result.get("content") or [{}])[0].get("text", "")
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


def packet_payload(data: dict) -> dict:
    src = data.get("evidence_packet") or data
    files = src.get("files") or data.get("files") or []
    code_chars = 0
    paths = []
    for f in files:
        if isinstance(f, dict):
            paths.append(f.get("path") or "")
            code_chars += len(str(f.get("code") or f.get("skeleton") or ""))
    tokens_field = data.get("tokens") or src.get("tokens") or {}
    selected = tokens_field.get("selected")
    packet_tok = tokens_field.get("packet")
    ws = src.get("workspace_tokens") or data.get("workspace_tokens")
    cov = src.get("coverage") or data.get("coverage")
    claim = cov.get("claim") if isinstance(cov, dict) else cov
    ret = src.get("retrieval") or data.get("retrieval") or {}
    return {
        "paths": paths,
        "nfiles": len(paths),
        "code_chars": code_chars,
        "json_bytes": len(json.dumps(data)),
        "selected_tokens": selected,
        "packet_tokens": packet_tok,
        "workspace_tokens": ws,
        "claim": claim,
        "conf": ret.get("confidence") or data.get("confidence"),
        "tier": ret.get("resolution_tier") or data.get("resolution_tier"),
    }


def usd(tokens_in: float, price_in_per_m: float) -> float:
    return (tokens_in / 1_000_000.0) * price_in_per_m


def main() -> int:
    bin_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\projects\neuromesh\target\release\neuromesh.exe"
    project = r"C:\projects\neuromesh"

    print("=" * 72)
    print("NeuroMesh MCP effectiveness bench v0.9.6")
    print("=" * 72)

    # --- CLI index timing ---
    print("\n[1] CLI index (warm re-index)")
    t0 = time.perf_counter()
    idx = subprocess.run([bin_path, "index"], cwd=project, capture_output=True, text=True, timeout=180)
    index_s = time.perf_counter() - t0
    for line in ((idx.stdout or "") + (idx.stderr or "")).splitlines():
        if any(k in line for k in ("Indexed", "Unchanged", "Graph Nodes", "Workspace Tokens", "File cap")):
            print("   ", line.strip())
    print(f"    index wall time: {index_s:.2f}s")

    # --- MCP session ---
    print("\n[2] MCP session metrics")
    c = Client(bin_path, ["mcp", project])
    metrics = ProcMetrics(c.proc.pid)
    t_boot = time.perf_counter()
    init = c.initialize()
    init_ms = (time.perf_counter() - t_boot) * 1000
    print(f"    initialize: {init_ms:.0f} ms  protocol={init['result'].get('protocolVersion')}")
    metrics.rss_mb()
    cpu0 = metrics.cpu_seconds_now()

    rows = []
    lat = []
    print("\n[3] Packet quality × latency × compression (12 prompts)")
    print(f"    {'prompt':42} {'ms':>6} {'files':>5} {'sel_tok':>8} {'pkt_tok':>8} {'reduce%':>8} {'bytes':>7} claim")
    for i, p in enumerate(PROMPTS):
        # mix pointer and minimal
        detail = "pointer" if i % 3 == 2 else "minimal"
        data, ms, err = c.tool("get_context_packet", {"task": p, "response_detail": detail})
        if err or data is None:
            print(f"    {p[:42]:42} FAIL {err}")
            continue
        st = packet_payload(data)
        sel = st["selected_tokens"] or max(1, int(st["code_chars"] / CHARS_PER_TOKEN))
        pkt = st["packet_tokens"] or int(st["json_bytes"] / CHARS_PER_TOKEN)
        # Prefer official selected vs workspace when present
        if st["workspace_tokens"] and sel:
            reduce_pct = max(0.0, (1.0 - sel / max(1, st["workspace_tokens"])) * 100.0)
        elif sel and pkt:
            # packet vs naive full-file attach proxy: use selected as "would have paid"
            reduce_pct = max(0.0, (1.0 - pkt / max(1, sel)) * 100.0) if detail == "pointer" else None
        else:
            reduce_pct = None
        # Official telemetry-style: vs workspace tokens
        if st["workspace_tokens"] and pkt:
            red_ws = (1.0 - pkt / max(1, st["workspace_tokens"])) * 100.0
        else:
            red_ws = None
        rows.append({**st, "ms": ms, "detail": detail, "sel": sel, "pkt": pkt, "red_ws": red_ws})
        lat.append(ms)
        metrics.rss_mb()
        red_s = f"{red_ws:7.1f}%" if red_ws is not None else "     n/a"
        print(f"    {p[:42]:42} {ms:6.0f} {st['nfiles']:5} {sel:8} {pkt:8} {red_s} {st['json_bytes']:7} {st['claim']}")

    cpu1 = metrics.cpu_seconds_now()
    cpu_used = (cpu1 - cpu0) if (cpu0 is not None and cpu1 is not None) else None

    # Warm latency on one query
    print("\n[4] Warm latency (pointer × 10)")
    warm = []
    for _ in range(10):
        _, ms, err = c.tool("get_context_packet", {
            "task": "How does is_safe_workspace work?",
            "response_detail": "pointer",
        })
        if not err:
            warm.append(ms)
            metrics.rss_mb()
    warm.sort()
    p50 = statistics.median(warm) if warm else None
    p95 = warm[int(len(warm) * 0.95) - 1] if warm else None
    print(f"    n={len(warm)} p50={p50:.0f}ms p95={p95:.0f}ms min={warm[0]:.0f} max={warm[-1]:.0f}" if warm else "    no samples")

    rss_end = metrics.rss_mb()
    print("\n[5] Process resources")
    print(f"    RSS end={rss_end:.1f} MB  peak={metrics.peak_rss:.1f} MB  samples={len(metrics.samples)}")
    if cpu_used is not None:
        print(f"    CPU user+kernel during bench: {cpu_used:.3f}s")
    print(f"    graph.bin size: ", end="")
    gbin = Path.home() / ".neuromesh" / "projects" / "neuromesh-d19a8510e0f841ca" / "graph.bin"
    if gbin.exists():
        print(f"{gbin.stat().st_size/1024/1024:.2f} MiB")
    else:
        print("n/a")

    c.close()

    # Concurrent
    print("\n[6] 3 concurrent MCP clients")
    clients = []
    rss_list = []
    t0 = time.perf_counter()
    try:
        for i in range(3):
            cl = Client(bin_path, ["mcp", project])
            m = ProcMetrics(cl.proc.pid)
            cl.initialize()
            rss_list.append(m)
            clients.append((cl, m))
        cl_lat = []
        for i, (cl, m) in enumerate(clients):
            _, ms, err = cl.tool("get_context_packet", {
                "task": "trace process_request_isolated",
                "response_detail": "pointer",
            })
            m.rss_mb()
            cl_lat.append(ms)
            print(f"    client{i+1}: {ms:.0f} ms  rss={m.samples[-1] if m.samples else '?':.0f} MB" if m.samples else f"    client{i+1}: {ms:.0f} ms")
        wall = time.perf_counter() - t0
        total_rss = sum(m.peak_rss for m in rss_list) or sum(m.samples[-1] for m in rss_list if m.samples)
        print(f"    wall={wall:.2f}s  total peak RSS={total_rss:.0f} MB")
    finally:
        for cl, _ in clients:
            cl.close()

    # --- Cost model ---
    print("\n[7] Token / cost estimate (per query, input-only context)")
    # Use average packet tokens across rows
    if rows:
        avg_pkt = statistics.mean(r["pkt"] for r in rows)
        avg_sel = statistics.mean(r["sel"] for r in rows)
        avg_red = statistics.mean([r["red_ws"] for r in rows if r["red_ws"] is not None]) if any(r["red_ws"] is not None for r in rows) else None
        naive_full = avg_sel  # proxy for "ship selected raw files"
        print(f"    avg packet tokens (agent pays):     {avg_pkt:,.0f}")
        print(f"    avg selected tokens (raw files):    {avg_sel:,.0f}")
        if avg_red is not None:
            print(f"    avg reduction vs workspace tokens:  {avg_red:.1f}%")
        for label, prices in PRICING.items():
            cost_pkt = usd(avg_pkt, prices["in"])
            cost_raw = usd(naive_full, prices["in"])
            saved = cost_raw - cost_pkt
            ratio = (cost_raw / cost_pkt) if cost_pkt > 0 else float("inf")
            print(f"    {label:14} packet=${cost_pkt:.6f}/q  raw=${cost_raw:.6f}/q  save={ratio:.1f}x  Δ=${saved:.6f}")
        # Session projection: 50 agent turns
        turns = 50
        print(f"    50-turn session (input context only):")
        for label, prices in list(PRICING.items())[:1]:
            print(f"      {label}: packet ${usd(avg_pkt*turns, prices['in']):.4f}  vs raw ${usd(naive_full*turns, prices['in']):.4f}")

    # Official CLI telemetry
    print("\n[8] Official neuromesh usage telemetry")
    try:
        usage = subprocess.run([bin_path, "usage"], cwd=project, capture_output=True, text=True, timeout=30)
        for line in ((usage.stdout or "") + (usage.stderr or "")).splitlines():
            if any(k in line.lower() for k in ("mean", "reduction", "requests", "tokens", "latency", "summary")):
                print("   ", line.strip())
    except Exception as e:
        print("    usage failed", e)

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    if rows:
        print(f"  prompts OK        : {len(rows)}/{len(PROMPTS)}")
        print(f"  latency p50/p95   : {statistics.median(lat):.0f} / {sorted(lat)[int(len(lat)*0.95)-1]:.0f} ms")
        print(f"  warm pointer p50  : {p50:.0f} ms" if p50 else "")
        print(f"  RSS peak (1 proc) : {metrics.peak_rss:.0f} MB")
        if cpu_used is not None:
            print(f"  CPU during bench  : {cpu_used:.2f}s")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
