#!/usr/bin/env python3
"""Head-to-head nm vs cbm MCP battery on the same repo and prompts."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT = r"C:\projects\neuromesh"

BATTERY = [
    ("symbol_exact", "find handle_tool_call and see what calls it", ["tools.rs", "handle_tool_call"]),
    ("root_fs_safety", "How does this tool prevent indexing dangerous paths like the filesystem root?", ["confine.rs", "is_safe_workspace", "is_filesystem_root"]),
    ("token_estimate", "How does the system estimate the number of tokens in a file or prompt?", ["token.rs", "TokenCounter"]),
    ("reinforcement", "How does a file's importance get reinforced after repeated edits?", ["synapse", "pheromone", "edge.rs", "Pheromone"]),
    ("retry_negative", "Is there retry logic or exponential backoff when calling the AI provider API?", []),  # expect weak/absent
    ("max_files_cap", "How does the system determine the maximum number of files to index automatically?", ["max_files", "FileCapArg", "commands/mod.rs"]),
    ("fa_symbol", "تابع handle_tool_call را پیدا کن و ببین چه چیزی آن را صدا می‌زند", ["tools.rs", "handle_tool_call"]),
]


class Mcp:
    def __init__(self, cmd: list[str], cwd: str):
        env = os.environ.copy()
        for k in ["WORKSPACE_FOLDER_PATHS", "VSCODE_CWD", "NEUROMESH_WORKSPACE", "PWD", "NEUROMESH_RESPONSE_DETAIL"]:
            env.pop(k, None)
        self.proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.q: queue.Queue = queue.Queue()
        self.pending = {}
        self.stderr = []
        self.nid = 1
        self.bytes_in = 0

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

    def wait(self, rid, t=60):
        end = time.time() + t
        while time.time() < end and rid not in self.pending:
            try:
                line = self.q.get(timeout=0.2)
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

    def init(self, root: str):
        self.rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "h2h", "version": "1"},
            "rootUri": f"file:///{root.replace('\\', '/')}",
            "workspaceFolders": [{"uri": f"file:///{root.replace('\\', '/')}", "name": "repo"}],
        })
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tools(self):
        resp = self.rpc("tools/list")
        if not resp:
            return []
        return [t.get("name") for t in resp.get("result", {}).get("tools", [])]

    def call(self, name, args, t=60):
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


def run_nm(bin_path: str) -> dict:
    c = Mcp([bin_path, "mcp", PROJECT], PROJECT)
    c.init(PROJECT)
    tools = c.tools()
    rows = []
    t_index = time.perf_counter()
    # ensure index warm via one packet
    c.call("get_context_packet", {"task": "warmup index", "response_detail": "pointer"})
    index_s = time.perf_counter() - t_index
    for qid, prompt, gold in BATTERY:
        t0 = time.perf_counter()
        data, ms, err = c.call("get_context_packet", {"task": prompt, "response_detail": "minimal"})
        blob = json.dumps(data) if data else ""
        files = []
        if data:
            src = data.get("evidence_packet") or data
            for f in src.get("files") or data.get("files") or []:
                if isinstance(f, dict):
                    files.append(f.get("path") or "")
                else:
                    files.append(str(f))
        hit = any(any(g.lower() in (p or "").lower() or g.lower() in blob.lower() for g in gold) for p in files) if gold else False
        weak = False
        if data:
            conf = data.get("confidence") or (data.get("retrieval") or {}).get("confidence")
            tier = data.get("resolution_tier") or (data.get("retrieval") or {}).get("resolution_tier")
            claim = data.get("coverage")
            if isinstance(claim, dict):
                claim = claim.get("claim")
            weak = tier == "no_confident_match" or (conf is not None and conf < 0.5) or claim in ("no_confident_match", "no_seed_resolved")
        rows.append({"id": qid, "ms": ms, "err": err, "hit": hit, "weak": weak, "bytes": len(blob), "files": files[:6]})
    rss = None
    try:
        import ctypes
        from ctypes import wintypes
        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        k32 = ctypes.WinDLL("kernel32"); ps = ctypes.WinDLL("psapi")
        h = k32.OpenProcess(0x1000, False, c.proc.pid)
        if h:
            pm = PMC(); pm.cb = ctypes.sizeof(pm)
            if ps.GetProcessMemoryInfo(h, ctypes.byref(pm), pm.cb):
                rss = pm.WorkingSetSize / (1024*1024)
            k32.CloseHandle(h)
    except Exception:
        pass
    out = {"tools": tools, "rows": rows, "bytes_in": c.bytes_in, "rss_mb": rss, "stderr": c.stderr[-5:]}
    c.close()
    return out


def run_cbm(exe: str) -> dict:
    c = Mcp([exe], PROJECT)
    c.init(PROJECT)
    tools = c.tools()
    # map our battery to cbm tools
    # try semantic_query / search_code / search_graph / get_architecture
    rows = []
    t_index = time.perf_counter()
    # try index
    for idx_name, idx_args in [
        ("index_repository", {"project": PROJECT}),
        ("index_repository", {"path": PROJECT}),
        ("index_repository", {}),
    ]:
        if idx_name in tools:
            data, ms, err = c.call(idx_name, idx_args, t=180)
            break
    index_s = time.perf_counter() - t_index
    for qid, prompt, gold in BATTERY:
        candidates = []
        if "semantic_query" in tools:
            candidates.append(("semantic_query", {"query": prompt, "project": PROJECT, "limit": 8}))
            candidates.append(("semantic_query", {"query": prompt, "limit": 8}))
        if "search_code" in tools:
            candidates.append(("search_code", {"query": prompt, "project": PROJECT}))
            candidates.append(("search_code", {"query": prompt}))
        if "search_graph" in tools:
            candidates.append(("search_graph", {"name_pattern": prompt[:40], "project": PROJECT}))
        best = None
        best_ms = 0
        err = None
        for name, args in candidates:
            data, ms, err = c.call(name, args, t=45)
            if data is not None:
                best = data
                best_ms = ms
                break
        blob = json.dumps(best) if best else ""
        hit = bool(gold) and any(g.lower() in blob.lower() for g in gold)
        rows.append({"id": qid, "ms": best_ms, "err": err, "hit": hit, "weak": False if hit else True, "bytes": len(blob), "files": []})
    rss = None
    try:
        import ctypes
        from ctypes import wintypes
        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        k32 = ctypes.WinDLL("kernel32"); ps = ctypes.WinDLL("psapi")
        h = k32.OpenProcess(0x1000, False, c.proc.pid)
        if h:
            pm = PMC(); pm.cb = ctypes.sizeof(pm)
            if ps.GetProcessMemoryInfo(h, ctypes.byref(pm), pm.cb):
                rss = pm.WorkingSetSize / (1024*1024)
            k32.CloseHandle(h)
    except Exception:
        pass
    out = {"tools": tools, "rows": rows, "bytes_in": c.bytes_in, "rss_mb": rss, "stderr": c.stderr[-5:], "index_s": index_s}
    c.close()
    return out


def score(name: str, res: dict, gold_pass: int, total: int) -> dict:
    rows = res["rows"]
    hits = sum(1 for r in rows if r["hit"])
    weak_ok = sum(1 for r in rows if r["weak"] and not r["hit"] and not BATTERY[[x[0] for x in BATTERY].index(r["id"])][2])
    errors = sum(1 for r in rows if r["err"])
    lat = [r["ms"] for r in rows if r["ms"]]
    p50 = sorted(lat)[len(lat)//2] if lat else 0
    avg_bytes = sum(r["bytes"] for r in rows) / max(1, len(rows))
    return {"name": name, "hits": hits, "errors": errors, "p50_ms": p50, "avg_bytes": avg_bytes, "rss_mb": res.get("rss_mb"), "ntools": len(res.get("tools") or [])}


def main() -> int:
    nm_bin = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yoose\.cargo\bin\neuromesh.exe"
    cbm = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\yoose\AppData\Local\Programs\codebase-memory-mcp\codebase-memory-mcp.exe"
    print("=" * 72)
    print("H2H: NeuroMesh vs codebase-memory-mcp")
    print("=" * 72)
    print("\n[NeuroMesh]")
    nm = run_nm(nm_bin)
    for r in nm["rows"]:
        mark = "HIT" if r["hit"] else ("WEAK" if r["weak"] else "MISS")
        print(f"  {r['id']:<18} {mark:<5} {r['ms']:5.0f}ms {r['bytes']:6}B  files={r['files'][:3]}")
    print(f"  tools={len(nm['tools'])} rss={nm['rss_mb']} bytes_in={nm['bytes_in']}")
    print("  stderr:", nm["stderr"])

    print("\n[CBM]")
    cbm_res = run_cbm(cbm)
    for r in cbm_res["rows"]:
        mark = "HIT" if r["hit"] else ("WEAK" if r["weak"] else "MISS")
        print(f"  {r['id']:<18} {mark:<5} {r['ms']:5.0f}ms {r['bytes']:6}B  err={str(r['err'])[:40] if r['err'] else ''}")
    print(f"  tools={len(cbm_res['tools'])} rss={cbm_res['rss_mb']} bytes_in={cbm_res['bytes_in']} index≈{cbm_res.get('index_s',0):.1f}s")
    print("  sample tools:", (cbm_res["tools"] or [])[:12])
    print("  stderr:", cbm_res["stderr"])

    print("\n" + "=" * 72)
    print("SCORES")
    print("=" * 72)
    nm_hits = sum(1 for r in nm["rows"] if r["hit"])
    nm_neg = sum(1 for r, (qid, _, gold) in zip(nm["rows"], BATTERY) if not gold and r["weak"])
    cbm_hits = sum(1 for r in cbm_res["rows"] if r["hit"])
    nm_p50 = sorted(r["ms"] for r in nm["rows"] if r["ms"])[len(nm["rows"])//2]
    cbm_ms = [r["ms"] for r in cbm_res["rows"] if r["ms"]]
    cbm_p50 = sorted(cbm_ms)[len(cbm_ms)//2] if cbm_ms else 0
    nm_avg_b = sum(r["bytes"] for r in nm["rows"])/len(nm["rows"])
    cbm_avg_b = sum(r["bytes"] for r in cbm_res["rows"])/len(cbm_res["rows"])
    print(f"Recall (6 positive):   nm {nm_hits}/6   cbm {cbm_hits}/6")
    print(f"Negatives honest:      nm {nm_neg}/1")
    print(f"Latency p50:           nm {nm_p50:.0f}ms   cbm {cbm_p50:.0f}ms")
    print(f"Avg payload:           nm {nm_avg_b:.0f}B   cbm {cbm_avg_b:.0f}B")
    print(f"RSS (session):         nm {nm['rss_mb']}MB   cbm {cbm_res['rss_mb']}MB")
    print(f"Tools listed:          nm {len(nm['tools'])}   cbm {len(cbm_res['tools'])}")
    print(f"Errors:                nm {sum(1 for r in nm['rows'] if r['err'])}   cbm {sum(1 for r in cbm_res['rows'] if r['err'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
