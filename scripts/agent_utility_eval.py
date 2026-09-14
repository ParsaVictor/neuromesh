#!/usr/bin/env python3
"""Agent-utility eval: realistic coding questions, packet usefulness vs noise."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

# (id, realistic agent task, gold symbols/paths that MUST appear, optional extras)
TASKS = [
    (
        "bugfix_stdin",
        "MCP hangs when the client sends garbage bytes on stdin — where is read_message and how does Content-Length framing work?",
        ["stdio.rs", "read_message", "Content-Length"],
    ),
    (
        "add_config",
        "How do I add a new max_graph_bytes config field so load_from refuses oversized graphs?",
        ["config.rs", "max_graph_bytes", "load_from"],
    ),
    (
        "workspace_switch",
        "When initialize sends a different rootUri, where does the server adopt the new workspace?",
        ["server.rs", "adopt_workspace", "initialize"],
    ),
    (
        "pointer_mode",
        "How does response_detail pointer serialize files without skeleton bodies?",
        ["response.rs", "pointer"],
    ),
    (
        "index_lock",
        "Where is the single-writer index lock taken so two MCP processes don't reindex together?",
        ["commands/mod.rs", "IndexLock", "try_acquire"],
    ),
    (
        "negative_does_not_exist",
        "Does this codebase implement GraphQL subscriptions for live graph updates?",
        [],  # should be honest miss
    ),
]


def run(bin_path: str) -> int:
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

    def pump(s, lab):
        for raw in iter(s.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if lab == "o" and line.strip():
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
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("id") == rid:
                pending[rid] = m
        return rid in pending

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "agent-util-eval", "version": "1"},
    }})
    wait(1)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    print("=" * 72)
    print("Agent utility eval — would I use this packet to start a fix?")
    print("=" * 72)
    useful = 0
    honest_neg = 0
    rid = 10
    for tid, task, gold in TASKS:
        t0 = time.perf_counter()
        send({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {
            "name": "get_context_packet",
            "arguments": {"task": task, "response_detail": "pointer"},
        }})
        wait(rid)
        ms = (time.perf_counter() - t0) * 1000
        data = json.loads(pending.pop(rid)["result"]["content"][0]["text"])
        files = [f.get("path", "") for f in data.get("files") or [] if isinstance(f, dict)]
        blob = json.dumps(data)
        claim = data.get("coverage")
        conf = data.get("confidence")
        tier = data.get("resolution_tier")
        hits = [g for g in gold if g.lower() in blob.lower() or any(g.lower() in p.lower() for p in files)]
        if not gold:
            ok = tier == "no_confident_match" or (conf is not None and conf < 0.5) or claim in ("no_seed_resolved", "no_confident_match")
            if ok:
                honest_neg += 1
            print(f"\n[{tid}] negative  {'HONEST' if ok else 'OVERCONFIDENT'} claim={claim} conf={conf} tier={tier}")
            print(f"  files={files[:4]}")
            continue
        pct = len(hits) / len(gold) if gold else 0
        good = pct >= 0.5
        if good:
            useful += 1
        print(f"\n[{tid}] {'USEFUL' if good else 'WEAK'} {ms:.0f}ms  gold {len(hits)}/{len(gold)}")
        print(f"  claim={claim} conf={conf}")
        print(f"  files={files[:5]}")
        print(f"  matched={hits}")

    # follow-up: expand if skeleton has folds
    send({"jsonrpc": "2.0", "id": 200, "method": "tools/call", "params": {
        "name": "get_context_packet",
        "arguments": {"task": "Fix Content-Length hang in read_message", "response_detail": "minimal"},
    }})
    wait(200)
    data = json.loads(pending.pop(200)["result"]["content"][0]["text"])
    folds = []
    for f in data.get("files") or []:
        folds.extend(f.get("folds") or [])
    if folds:
        f0 = folds[0]
        fid = f0 if isinstance(f0, str) else (f0.get("fold_id") if isinstance(f0, dict) else None)
        if not fid:
            print("\n[expand_fold] no fold_id")
        else:
            t0 = time.perf_counter()
            send({"jsonrpc": "2.0", "id": 201, "method": "tools/call", "params": {
                "name": "neuromesh_expand_fold", "arguments": {"fold_id": fid},
            }})
            wait(201)
            exp = pending.pop(201)
            ms = (time.perf_counter() - t0) * 1000
            body = exp.get("result", {}).get("content", [{}])[0].get("text", "")
            print(f"\n[expand_fold] {ms:.0f}ms body_len={len(body)} fold={fid}")
    else:
        print("\n[expand_fold] no folds in packet")

    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

    print("\n" + "=" * 72)
    print(f"USEFUL for agent start: {useful}/{len([t for t in TASKS if t[2]])}")
    print(f"HONEST negatives: {honest_neg}/1")
    print("=" * 72)
    return 0 if useful >= 4 else 1


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yoose\.cargo\bin\neuromesh.exe"))
