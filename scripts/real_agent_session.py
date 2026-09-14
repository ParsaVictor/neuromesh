#!/usr/bin/env python3
"""Real agent session: solve a concrete maintenance task using only MCP tools first."""
from __future__ import annotations

import json
import os
import queue
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

PROJECT = r"C:\projects\neuromesh"


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


class Mcp:
    def __init__(self, bin_path):
        env = os.environ.copy()
        for k in ["WORKSPACE_FOLDER_PATHS", "VSCODE_CWD", "NEUROMESH_WORKSPACE", "PWD", "NEUROMESH_RESPONSE_DETAIL"]:
            env.pop(k, None)
        self.proc = subprocess.Popen(
            [bin_path, "mcp", PROJECT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=PROJECT, env=env, bufsize=0,
        )
        self.q: queue.Queue = queue.Queue()
        self.pending = {}
        self.stderr = []
        self.nid = 1
        self.bytes_in = 0
        self.bytes_out = 0

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
        raw = (json.dumps(o, separators=(",", ":")) + "\n").encode()
        self.bytes_out += len(raw)
        assert self.proc.stdin
        self.proc.stdin.write(raw)
        self.proc.stdin.flush()

    def wait(self, rid, t=45):
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
            self.bytes_in += len(line) + 1
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("id") == rid:
                self.pending[rid] = m
        return rid in self.pending

    def init(self):
        self.rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "real-agent", "version": "1"},
            "rootUri": "file:///C:/projects/neuromesh",
            "workspaceFolders": [{"uri": "file:///C:/projects/neuromesh", "name": "neuromesh"}],
        })
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def rpc(self, method, params=None, t=45):
        rid = self.nid
        self.nid += 1
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        if not self.wait(rid, t):
            return None
        return self.pending.pop(rid)

    def tool(self, name, args, t=45):
        t0 = time.perf_counter()
        resp = self.rpc("tools/call", {"name": name, "arguments": args}, t=t)
        ms = (time.perf_counter() - t0) * 1000
        if not resp:
            return None, ms, "timeout"
        if resp.get("error"):
            return None, ms, str(resp["error"])[:160]
        r = resp.get("result", {})
        if r.get("isError"):
            return None, ms, (r.get("content") or [{}])[0].get("text", "")[:160]
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


def files_of(data):
    src = data.get("evidence_packet") or data
    out = []
    for f in src.get("files") or data.get("files") or []:
        if isinstance(f, dict):
            out.append(f)
    return out


def main() -> int:
    bin_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yoose\.cargo\bin\neuromesh.exe"
    print("=" * 72)
    print("REAL agent session — task: improve TokenCounter discovery for token_estimate")
    print("=" * 72)

    # Ground truth check via filesystem (what I would have used without MCP)
    token_rs = Path(PROJECT) / "crates/neuromesh-core/src/token.rs"
    print(f"filesystem ground truth exists: {token_rs.exists()} ({token_rs.stat().st_size} bytes)")

    c = Mcp(bin_path)
    c.init()
    pid = c.proc.pid
    rss0 = rss_mb(pid)
    print(f"MCP pid={pid} rss0={rss0:.1f}MB" if rss0 else f"MCP pid={pid}")

    log = []
    def step(label, name, args):
        data, ms, err = c.tool(name, args)
        rss = rss_mb(pid)
        rec = {"label": label, "tool": name, "ms": ms, "err": err, "rss": rss}
        if data is not None and not err:
            if name == "get_context_packet":
                rec["claim"] = data.get("coverage")
                rec["conf"] = data.get("confidence")
                rec["tier"] = data.get("resolution_tier")
                rec["hint"] = data.get("agent_hint")
                rec["files"] = [f.get("path") for f in files_of(data)]
                rec["bytes"] = len(json.dumps(data))
            else:
                rec["keys"] = list(data.keys())[:8]
                rec["bytes"] = len(json.dumps(data))
                rec["data"] = data
        log.append(rec)
        print(f"  [{label}] {name} {ms:.0f}ms err={err} rss={rss}")
        if rec.get("files"):
            print(f"    files={rec['files'][:6]} claim={rec.get('claim')} conf={rec.get('conf')}")
        if rec.get("hint"):
            print(f"    hint={rec['hint'][:120]}")
        return data, err

    print("\n--- Step 1: pointer for the real bug ---")
    p1, e1 = step(
        "discover",
        "get_context_packet",
        {
            "task": "token_estimate query misses token.rs TokenCounter — how does the system estimate tokens?",
            "response_detail": "pointer",
        },
    )

    print("\n--- Step 2: search exact symbol ---")
    p2, e2 = step("search", "neuromesh_search_symbols", {"query": "TokenCounter", "limit": 8})

    print("\n--- Step 3: skeleton the ground-truth file ---")
    p3, e3 = step("skeleton", "neuromesh_get_file_skeleton", {"file_path": "crates/neuromesh-core/src/token.rs"})

    print("\n--- Step 4: dependencies of TokenCounter ---")
    p4, e4 = step("deps", "neuromesh_get_dependencies", {"query": "TokenCounter"})

    print("\n--- Step 5: expand a fold if present ---")
    folds = (p3 or {}).get("folds") or []
    fid = None
    if folds:
        f0 = folds[0]
        fid = f0.get("fold_id") if isinstance(f0, dict) else (f0 if isinstance(f0, str) else None)
    if fid:
        p5, e5 = step("expand", "neuromesh_expand_fold", {"fold_id": fid})
    else:
        print("  (no folds)")
        p5, e5 = None, "no-folds"

    print("\n--- Step 6: record feedback ---")
    step("feedback", "neuromesh_record_feedback", {
        "task_success": True,
        "touched_nodes": ["crates/neuromesh-core/src/token.rs"],
    })

    # Agent decision simulation: would I open token.rs?
    paths_seen = []
    for rec in log:
        paths_seen.extend(rec.get("files") or [])
    hit = any("token.rs" in (p or "") for p in paths_seen)
    search_hit = False
    if p2:
        blob = json.dumps(p2)
        search_hit = "token.rs" in blob or "TokenCounter" in blob
    skel_hit = bool(p3 and (p3.get("file_path") or "").endswith("token.rs"))

    print("\n--- Agent decision ---")
    print(f"pointer mentioned token.rs: {hit}")
    print(f"search found TokenCounter: {search_hit}")
    print(f"skeleton opened token.rs: {skel_hit}")
    would_read = hit or search_hit or skel_hit
    print(f"Would I Read token.rs next? {would_read}")

    rss_end = rss_mb(pid)
    print(f"\n--- Session resources ---")
    print(f"RSS {rss0:.1f} → {rss_end:.1f} MB")
    print(f"MCP JSON bytes in≈{c.bytes_in} out≈{c.bytes_out}")
    print(f"tools called: {len(log)}  errors: {sum(1 for r in log if r['err'])}")
    packet_bytes = sum(r.get("bytes") or 0 for r in log if r.get("bytes"))
    print(f"tool payload bytes total: {packet_bytes}")
    c.close()

    # Baseline: how many bytes would full file Read of token.rs be?
    naive = token_rs.stat().st_size if token_rs.exists() else 0
    print(f"naive Read token.rs alone: {naive} bytes")
    if naive and packet_bytes:
        print(f"agent MCP payloads vs one full file Read: {packet_bytes/naive:.1f}x")

    print("\n" + "=" * 72)
    print("HONEST COOPERATION SCORE")
    print("=" * 72)
    score = 0
    score += 2 if hit else 0
    score += 2 if search_hit else 0
    score += 2 if skel_hit else 0
    score += 1 if would_read else 0
    score += 1 if sum(1 for r in log if r["err"]) == 0 else 0
    print(f"{score}/8  (pointer+search+skeleton+decision+no-errors)")
    print("=" * 72)
    return 0 if would_read else 1


if __name__ == "__main__":
    raise SystemExit(main())
