#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NeuroMesh `fast`-engine regression battery.

Self-contained reproduction of the 7-query test used to track accuracy across
v0.7.17 -> v0.9.7. Run against the `neuromesh` repo itself (this script assumes
it is being run from the repo root, after `neuromesh config engine fast --yes`
and `neuromesh index --max-files auto`).

Usage:
    python3 nm_regression_battery.py [path-to-repo]

Exit code is non-zero if any REQUIRED case fails, so this can be wired into CI.
"""
import subprocess, json, time, re, os, sys

REPO = sys.argv[1] if len(sys.argv) > 1 else "."

# Each case: (id, task, required, any-of ground-truth path fragments, human note)
# "required=True" cases failing should block a release; "required=False" are
# tracked but non-blocking (e.g. still-open, previously-reported issues).
CASES = [
    dict(
        id="symbol_exact",
        task="find handle_tool_call and see what calls it",
        required=True,
        expect_any=["neuromesh-mcp/src/tools.rs"],
        note="Exact symbol lookup — baseline sanity check.",
    ),
    dict(
        id="root_fs_safety",
        task="How does this tool prevent indexing dangerous paths like the filesystem root?",
        required=True,
        expect_any=["neuromesh-index/src/confine.rs"],
        note="Conceptual query, no literal keyword overlap. Fixed in v0.9.5, regression-tested since.",
    ),
    dict(
        id="token_estimate",
        task="How does the system estimate the number of tokens in a file or prompt?",
        required=True,
        expect_any=["neuromesh-core/src/token.rs", "TokenCounter"],
        note="OPEN REGRESSION since v0.9.6: ground-truth file (token.rs/TokenCounter) is absent; "
             "returns unrelated session/orchestrator seeds instead.",
    ),
    dict(
        id="reinforcement",
        task="How does a file's importance get reinforced after repeated edits?",
        required=True,
        expect_any=["neuromesh-graph/src/edge.rs", "neuromesh-graph/src/synapse.rs", "PheromoneEngine"],
        note="Was `no_seed_resolved` (empty) through v0.9.4. Fixed in v0.9.5, holding through v0.9.7.",
    ),
    dict(
        id="retry_negative",
        task="Is there retry logic or exponential backoff when calling the AI provider API?",
        required=True,
        expect_any=["no_confident_match", '"coverage":"no_confident_match"'],
        note="FIXED in v0.9.7 (was open since v0.8.2): tool now returns coverage:\"no_confident_match\" "
             "instead of the misleading coverage:\"bounded\" it used to return for this same query. "
             "It still surfaces identifiers.rs:api_path_alias as the closest (non-matching) candidate, "
             "which is fine — the fix that mattered was the explicit low-confidence label, not "
             "necessarily suppressing the candidate entirely.",
    ),
    dict(
        id="max_files_cap",
        task="How does the system determine the maximum number of files to index automatically?",
        required=True,
        expect_any=["max_files_from_args", "FileCapArg"],
        note="Was returning an unrelated VS Code extension file + test fixture through v0.9.4. "
             "Fixed in v0.9.5, holding through v0.9.7.",
    ),
    dict(
        id="fa_symbol",
        task="تابع handle_tool_call را پیدا کن و ببین چه چیزی آن را صدا می‌زند",
        required=True,
        expect_any=["neuromesh-mcp/src/tools.rs"],
        note="Same symbol lookup as symbol_exact, in Persian — sanity check that literal "
             "identifiers embedded in non-English text still resolve.",
    ),
]


def mcp_call(proc, msg_id, method, params):
    req = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}
    proc.stdin.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line)


def main():
    proc = subprocess.Popen(
        ["neuromesh", "mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=REPO,
    )
    mcp_call(proc, 1, "initialize", {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "nm-regression-battery", "version": "1.0"},
    })
    proc.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}) + "\n").encode())
    proc.stdin.flush()

    print(f"{'ID':<16} {'REQ':<4} {'RESULT':<6} {'ms':>7}  TASK")
    print("-" * 100)

    blocking_failures = []
    msgid = 100
    for case in CASES:
        t0 = time.time()
        r = mcp_call(proc, msgid, "tools/call", {"name": "get_context_packet", "arguments": {"task": case["task"]}})
        msgid += 1
        t1 = time.time()
        try:
            txt = r["result"]["content"][0]["text"]
        except Exception:
            txt = json.dumps(r, ensure_ascii=False)

        passed = any(fragment in txt for fragment in case["expect_any"])
        status = "PASS" if passed else "FAIL"
        print(f"{case['id']:<16} {'yes' if case['required'] else 'no':<4} {status:<6} {round((t1-t0)*1000):>6}  {case['task'][:60]}")
        if not passed:
            print(f"    note: {case['note']}")
            if case["required"]:
                blocking_failures.append(case["id"])

    proc.terminate()

    print("-" * 100)
    if blocking_failures:
        print(f"RESULT: {len(blocking_failures)} required case(s) failed: {', '.join(blocking_failures)}")
        sys.exit(1)
    else:
        print("RESULT: all required cases passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
