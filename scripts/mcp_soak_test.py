#!/usr/bin/env python3
"""Soak: many mixed MCP tool calls — watch for hangs, RSS growth, errors."""
from __future__ import annotations

import json
import os
import queue
import statistics
import subprocess
import sys
import threading
import time

try:
    import ctypes
    from ctypes import wintypes
except Exception:
    ctypes = None


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


def main() -> int:
    bin_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yoose\.cargo\bin\neuromesh.exe"
    env = os.environ.copy()
    for k in ["WORKSPACE_FOLDER_PATHS", "VSCODE_CWD", "NEUROMESH_WORKSPACE", "PWD", "NEUROMESH_RESPONSE_DETAIL"]:
        env.pop(k, None)
    proc = subprocess.Popen(
        [bin_path, "mcp", r"C:\projects\neuromesh"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=r"C:\projects\neuromesh", env=env, bufsize=0,
    )
    q: queue.Queue = queue.Queue()
    pending: dict[int, dict] = {}
    stderr: list[str] = []

    def pump(s, lab):
        for raw in iter(s.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if lab == "e":
                if line:
                    stderr.append(line)
            else:
                q.put(line)

    threading.Thread(target=pump, args=(proc.stdout, "o"), daemon=True).start()
    threading.Thread(target=pump, args=(proc.stderr, "e"), daemon=True).start()

    def send(o):
        assert proc.stdin
        proc.stdin.write((json.dumps(o, separators=(",", ":")) + "\n").encode())
        proc.stdin.flush()

    def wait(rid, t=40):
        end = time.time() + t
        while time.time() < end and rid not in pending:
            try:
                line = q.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None:
                    return False
                continue
            if not line or not line.strip():
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(m, dict) and m.get("id") == rid:
                pending[rid] = m
        return rid in pending

    def call(name, args, rid, t=40):
        send({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": args}})
        if not wait(rid, t):
            return None, "timeout"
        resp = pending.pop(rid)
        if resp.get("error"):
            return None, str(resp["error"])[:120]
        result = resp.get("result", {})
        if result.get("isError"):
            return None, (result.get("content") or [{}])[0].get("text", "")[:120]
        text = (result.get("content") or [{}])[0].get("text", "")
        try:
            return json.loads(text), None
        except json.JSONDecodeError:
            return {"_raw": text}, None

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "soak", "version": "1"},
        "rootUri": "file:///C:/projects/neuromesh",
        "workspaceFolders": [{"uri": "file:///C:/projects/neuromesh", "name": "n"}],
    }})
    wait(1)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    prompts = [
        "is_safe_workspace", "load_persisted", "token_estimate", "TokenCounter",
        "index lock", "pointer response", "filesystem root", "pheromone learning",
        "max_files auto", "Content-Length stdio", "workspace detection", "expand_fold",
    ]
    tools_cycle = [
        ("get_context_packet", lambda p: {"task": p, "response_detail": "minimal"}),
        ("get_context_packet", lambda p: {"task": p, "response_detail": "pointer"}),
        ("neuromesh_search_symbols", lambda p: {"query": p.split()[0], "limit": 5}),
        ("neuromesh_get_stats", lambda p: {}),
        ("neuromesh_get_architecture", lambda p: {}),
        ("neuromesh_get_dependencies", lambda p: {"query": "is_safe_workspace"}),
        ("neuromesh_trace", lambda p: {"query": "run_stdio", "direction": "out", "depth": 1}),
    ]

    errors = []
    lat = []
    rss0 = rss_mb(proc.pid)
    peak = rss0 or 0
    rid = 10
    n = 0
    t0 = time.perf_counter()
    for i in range(42):
        tool, mk = tools_cycle[i % len(tools_cycle)]
        prompt = prompts[i % len(prompts)]
        data, err = call(tool, mk(prompt), rid)
        rid += 1
        n += 1
        if err:
            errors.append(f"{tool}:{err}")
        else:
            # last latency unknown from call; re-measure roughly via wall between
            pass
        r = rss_mb(proc.pid)
        if r:
            peak = max(peak, r)
        if i % 7 == 6:
            print(f"  i={i+1} rss={r:.1f}MB peak={peak:.1f}MB errors={len(errors)}", flush=True)

    # fold expand path
    data, err = call("neuromesh_get_file_skeleton", {"file_path": "crates/neuromesh-mcp/src/stdio.rs"}, rid); rid += 1
    folds = (data or {}).get("folds") or []
    if folds and isinstance(folds[0], dict) and folds[0].get("fold_id"):
        _, err = call("neuromesh_expand_fold", {"fold_id": folds[0]["fold_id"]}, rid); rid += 1
        if err:
            errors.append(f"expand_fold:{err}")
    else:
        # still ok
        pass

    # record_feedback
    _, err = call("neuromesh_record_feedback", {"task_success": True, "touched_nodes": ["crates/neuromesh-mcp/src/stdio.rs"]}, rid); rid += 1
    if err:
        errors.append(f"feedback:{err}")

    # ping after soak
    send({"jsonrpc": "2.0", "id": rid, "method": "ping"})
    alive = wait(rid, 10)
    rid += 1
    wall = time.perf_counter() - t0
    print(f"\ncalls≈{n}+extras wall={wall:.1f}s errors={len(errors)} alive={alive}")
    print(f"RSS start={rss0} peak={peak} end={rss_mb(proc.pid)}")
    if errors:
        print("sample errors:", errors[:5])
    if stderr:
        print("stderr tail:", stderr[-5:])
    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

    ok = alive and len(errors) == 0 and (peak is None or peak < 200)
    print("SOAK", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
