#!/usr/bin/env python3
"""Class check: many 'find X and show implementation' queries must include fn X."""
import json, os, subprocess, threading, queue, time, sys

CASES = [
    ("find the reinforce_path function", "fn reinforce_path"),
    ("find handle_tool_call and show its implementation", "async fn handle_tool_call"),
    ("find is_safe_workspace", "fn is_safe_workspace"),
    ("find path_stem_overlap and show code", "fn path_stem_overlap"),
    ("find extract_seed_windows", "fn extract_seed_windows"),
    ("find package_slug", "fn package_slug"),
    ("find term_is_standalone", "fn term_is_standalone"),
    ("find analyze_impact", "fn analyze_impact"),
    ("find write_snapshot_bytes", "fn write_snapshot_bytes"),
    ("find seed_file_paths", "fn seed_file_paths"),
]

def run(binp):
    env = os.environ.copy()
    for k in ["WORKSPACE_FOLDER_PATHS", "VSCODE_CWD", "NEUROMESH_WORKSPACE", "PWD", "NEUROMESH_RESPONSE_DETAIL"]:
        env.pop(k, None)
    p = subprocess.Popen(
        [binp, "mcp", r"C:\projects\neuromesh"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=r"C:\projects\neuromesh", env=env, bufsize=0,
    )
    q = queue.Queue(); pending = {}
    def pump(s, l):
        for raw in iter(s.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if l == "o" and line.strip():
                q.put(line)
    threading.Thread(target=pump, args=(p.stdout, "o"), daemon=True).start()
    threading.Thread(target=pump, args=(p.stderr, "e"), daemon=True).start()
    def send(o):
        p.stdin.write((json.dumps(o, separators=(",", ":")) + "\n").encode()); p.stdin.flush()
    def wait(i, t=60):
        end = time.time() + t
        while time.time() < end and i not in pending:
            try:
                line = q.get(timeout=0.2)
            except queue.Empty:
                if p.poll() is not None:
                    return False
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("id") == i:
                pending[i] = m
        return i in pending
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "seed-class", "version": "1"},
    }})
    wait(1)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    ok = fail = 0
    rid = 10
    for task, needle in CASES:
        t0 = time.perf_counter()
        send({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {
            "name": "get_context_packet",
            "arguments": {"task": task},
        }})
        wait(rid)
        ms = (time.perf_counter() - t0) * 1000
        text = pending.pop(rid)["result"]["content"][0]["text"]
        has = needle in text
        status = "PASS" if has else "FAIL"
        if has:
            ok += 1
        else:
            fail += 1
        print(f"  {status}  {ms:5.0f}ms {len(text):6}B  {needle:28}  {task[:48]}")
        rid += 1
    p.kill()
    print(f"\nRESULT: {ok}/{len(CASES)} seed bodies present  ({fail} fail)")
    return 0 if fail == 0 else 1

if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yoose\.cargo\bin\neuromesh.exe"))
