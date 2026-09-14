#!/usr/bin/env python3
"""Head-to-head: NeuroMesh vs codebase-memory-mcp on the same discovery battery."""
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
NM = r"C:\Users\yoose\.cargo\bin\neuromesh.exe"
CBM = r"C:\Users\yoose\AppData\Local\Programs\codebase-memory-mcp\codebase-memory-mcp.exe"

# (id, prompt, gold path fragments)
CASES = [
    ("symbol_exact", "find handle_tool_call and see what calls it", ["neuromesh-mcp/src/tools.rs"]),
    ("root_fs_safety", "How does this tool prevent indexing dangerous paths like the filesystem root?", ["neuromesh-index/src/confine.rs"]),
    ("token_estimate", "How does the system estimate the number of tokens in a file or prompt?", ["neuromesh-core/src/token.rs", "TokenCounter"]),
    ("reinforcement", "How does a file's importance get reinforced after repeated edits?", ["neuromesh-graph/src/edge.rs", "neuromesh-graph/src/synapse.rs", "Pheromone"]),
    ("retry_negative", "Is there retry logic or exponential backoff when calling the AI provider API?", []),  # expect empty/weak
    ("max_files_cap", "How does the system determine the maximum number of files to index automatically?", ["max_files_from_args", "FileCapArg"]),
    ("fa_symbol", "تابع handle_tool_call را پیدا کن و ببین چه چیزی آن را صدا می‌زند", ["neuromesh-mcp/src/tools.rs"]),
]


class Mcp:
    def __init__(self, cmd, cwd=None):
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
                line = self.q.get(timeout=0.2)
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

    def init(self, name):
        self.rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": name, "version": "1"},
        })
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = self.rpc("tools/list", t=30)
        names = []
        if tools:
            names = [t.get("name") for t in tools.get("result", {}).get("tools", [])]
        return names

    def tool(self, name, args, t=60):
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


def hit(blob: str, gold: list[str]) -> bool:
    if not gold:
        return False
    b = blob.lower()
    return any(g.lower() in b for g in gold)


def run_nm(c: Mcp, prompt: str):
    data, ms, err = c.tool("get_context_packet", {"task": prompt, "response_detail": "pointer"})
    if err or data is None:
        return None, ms, err, 0
    blob = json.dumps(data, ensure_ascii=False)
    return data, ms, None, len(blob)


def run_cbm(c: Mcp, prompt: str):
    last = (None, 0.0, "no-attempt", 0, "none")
    for name, args in [
        ("search_graph", {"project": "neuromesh", "query": prompt}),
        ("search_code", {"project": "neuromesh", "pattern": (prompt.split()[0] if prompt else "x")}),
    ]:
        data, ms, err = c.tool(name, args, t=45)
        last = (data, ms, err, 0 if data is None else len(json.dumps(data)), name)
        if data is not None and not err and last[3] > 80:
            return last
    return last


def main() -> int:
    print("=" * 72)
    print("Head-to-head: NeuroMesh 0.9.9 vs codebase-memory-mcp 0.10.8")
    print("Repo: C:\\projects\\neuromesh")
    print("=" * 72)

    # Ensure cbm has an index
    print("\n[cbm] ensuring index…")
    t0 = time.perf_counter()
    idx = subprocess.run(
        [CBM, "cli", "index_repository", json.dumps({"repo_path": PROJECT, "mode": "fast"})],
        capture_output=True, text=True, timeout=180,
    )
    print(f"  index exit={idx.returncode} {time.perf_counter()-t0:.1f}s")
    if idx.returncode != 0:
        print((idx.stdout or "")[-400:], (idx.stderr or "")[-400:])

    nm = Mcp([NM, "mcp", PROJECT], PROJECT)
    nm_tools = nm.init("h2h-nm")
    cbm = Mcp([CBM], PROJECT)
    cbm_tools = cbm.init("h2h-cbm")

    print(f"nm tools ({len(nm_tools)}): {nm_tools[:8]}…")
    print(f"cbm tools ({len(cbm_tools)}): {cbm_tools[:8]}…")

    rows = []
    for cid, prompt, gold in CASES:
        n_data, n_ms, n_err, n_bytes = run_nm(nm, prompt)
        c_data, c_ms, c_err, c_bytes, c_tool = run_cbm(cbm, prompt)
        n_blob = json.dumps(n_data, ensure_ascii=False) if n_data else ""
        c_blob = json.dumps(c_data, ensure_ascii=False) if c_data else ""
        n_hit = hit(n_blob, gold) if gold else False
        c_hit = hit(c_blob, gold) if gold else False
        # negative honesty
        n_neg = False
        if not gold and n_data:
            claim = n_data.get("coverage")
            conf = n_data.get("confidence")
            tier = n_data.get("resolution_tier")
            n_neg = tier == "no_confident_match" or (conf is not None and conf < 0.5)
        c_neg = (not gold) and (not c_hit)
        rows.append({
            "id": cid, "gold": bool(gold),
            "n_ms": n_ms, "n_bytes": n_bytes, "n_hit": n_hit, "n_err": n_err, "n_neg": n_neg,
            "c_ms": c_ms, "c_bytes": c_bytes, "c_hit": c_hit, "c_err": c_err, "c_tool": c_tool, "c_neg": c_neg,
        })
        print(f"\n[{cid}]")
        print(f"  nm  {n_ms:6.0f}ms {n_bytes:6}B hit={n_hit} err={n_err}")
        print(f"  cbm {c_ms:6.0f}ms {c_bytes:6}B via={c_tool} hit={c_hit} err={c_err}")

    nm.close()
    cbm.close()

    pos = [r for r in rows if r["gold"]]
    neg = [r for r in rows if not r["gold"]]
    n_recall = sum(1 for r in pos if r["n_hit"]) / max(1, len(pos))
    c_recall = sum(1 for r in pos if r["c_hit"]) / max(1, len(pos))
    n_neg_ok = sum(1 for r in neg if r["n_neg"]) / max(1, len(neg))
    c_neg_ok = sum(1 for r in neg if r["c_neg"]) / max(1, len(neg))
    n_ms = [r["n_ms"] for r in rows if r["n_err"] is None]
    c_ms = [r["c_ms"] for r in rows if r["c_err"] is None]
    n_by = sum(r["n_bytes"] for r in rows)
    c_by = sum(r["c_bytes"] for r in rows)

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"recall  nm={n_recall:.0%}  cbm={c_recall:.0%}   ({len(pos)} positive)")
    print(f"neg.    nm={n_neg_ok:.0%}  cbm={c_neg_ok:.0%}   ({len(neg)} negative)")
    def p50(xs):
        if not xs:
            return float("nan")
        s = sorted(xs)
        return s[len(s) // 2]
    print(f"latency nm p50={p50(n_ms):.0f}ms  cbm p50={p50(c_ms):.0f}ms")
    print(f"bytes   nm={n_by}  cbm={c_by}  ratio nm/cbm={n_by/max(1,c_by):.1f}x")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
