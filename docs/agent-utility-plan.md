# NeuroMesh agent-utility plan (evidence-based)

Grounded in live measurements on `C:\projects\neuromesh` (v0.9.9, 2026-09-15). No guesses.

## Measured baseline (this repo)

| Metric | Value |
|---|---|
| Seed-body class | **10/10** (`scripts/seed_body_class_test.py`) |
| External battery | **7/7** (`scripts/nm_regression_battery.py`) |
| Quality 15-prompt | recall **100%** · negatives honest |
| Agent session | 5/5 useful · RSS **~35MB** · naive/agent tokens **~7×** |
| Telemetry | **~93%** mean reduction vs workspace |
| Pointer p50 | **~50–90ms** |
| vs cbm (unbiased) | nm better NL recall; cbm faster queries / less RAM / more languages |

## Why agents should rely on nm (contract)

```
target unknown → get_context_packet (pointer first)
  → next.example_args (copy-paste MCP call)
  → neuromesh_search_symbols / get_file_skeleton
  → expand_fold only if needed
  → Read/patch
  → record_feedback

target known → path_hints or get_file_skeleton / Read (skip full packet)
```

`initialize` instructions and `next.example_args` encode this loop.

## Cost levers (done / remaining)

| Lever | Status | Effect |
|---|---|---|
| pointer lean | done | ~4KB |
| minimal ≤2 bodies + seed window | done | seed body present; ~15–20KB worst case |
| trace/impact depth=1 + caps | done | 265KB→21KB, 414KB→2KB |
| omit empty JSON | done | ~21% on trace records |
| NEUROMESH_RESPONSE_DETAIL | done | deploy default |
| sharding >64MB graphs | done | monorepo safety |

## Accuracy levers (done / remaining)

| Lever | Status |
|---|---|
| multi-concept aliases | done |
| standalone word matching | done |
| non-Latin hybrid bridge | done |
| no_confident_match on weak hits | done |
| connector noise penalty | done |
| **remaining: hybrid/deep on 162-lang style corpora** | needs embedding work (cbm still stronger) |

## Near-zero error profile (measured)

| Check | Result |
|---|---|
| hostiles + garbage stdin | loop alive |
| 40+ soak | 0 errors, RSS flat |
| AppData refuse | yes |
| clippy/unit | green |

## Agent collaboration (special languages / cases)

| Case | Mechanism |
|---|---|
| Persian/CJK/Cyrillic NL | `has_non_latin_script` + alias clusters |
| camelCase symbol | generic verb clusters suppressed |
| negative existence | conf + `no_confident_match` + `next` |
| known path | `path_hints` / skip packet |

## Recommended daily profile

```json
{
  "env": { "NEUROMESH_RESPONSE_DETAIL": "pointer" }
}
```

Pointer-first; expand only when reading the body.

## Next (only if a new measured gap appears)

1. Faster cold pointer (first call ~700ms) — warmup thread for seed files
2. Deeper structural parity with cbm LSP — only with a real multi-repo benchmark
3. Hybrid engine quality on non-English — before more NL claims

Do not ship speculative features without a failing battery case first.
