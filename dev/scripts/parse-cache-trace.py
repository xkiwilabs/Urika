#!/usr/bin/env python3
"""Parse a URIKA_PROMPT_TRACE_FILE JSONL and report cache stats.

Reports:
  1. Per-agent table: total calls, cache_read tokens, total input tokens,
     cache hit ratio.
  2. System-prompt size stability: for each agent, list distinct
     system_bytes values seen — should be 1 per agent if Tier 1
     reorder + rec #2 + rec #3 are working.
  3. Cross-experiment delta: for each per-experiment role (task,
     planning, evaluator, advisor), compare the FIRST call's
     cache_read_in vs LATER calls'. The first call ever pays full
     creation cost (cache miss is unavoidable). Within an experiment,
     turn-2+ should hit cache. ACROSS experiments, turn-1 of
     experiment-2 should ALSO hit cache (the v0.4.3 win).

Usage:
    parse-cache-trace.py <path-to-trace.jsonl>
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <trace.jsonl>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    records: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  warn: skipping malformed line: {e}", file=sys.stderr)

    if not records:
        print("  (no records in trace)")
        return 0

    print(f"  parsed {len(records)} agent calls")
    print()

    # --- Per-agent summary table ---
    by_agent: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_agent[r.get("agent", "?")].append(r)

    print("PER-AGENT CACHE SUMMARY")
    print(f"  {'agent':<22} {'calls':>6} {'sys_bytes':>10} {'cache_read':>12} "
          f"{'cache_create':>14} {'input':>10} {'hit_ratio':>10}")
    print("  " + "-" * 90)
    totals = {"calls": 0, "cache_read": 0, "cache_create": 0, "input": 0}
    for agent in sorted(by_agent):
        rs = by_agent[agent]
        sys_bytes_set = {r.get("system_bytes", 0) for r in rs}
        sys_label = (
            str(next(iter(sys_bytes_set)))
            if len(sys_bytes_set) == 1
            else f"{min(sys_bytes_set)}-{max(sys_bytes_set)}"
        )
        cache_read = sum(r.get("cache_read_in", 0) or 0 for r in rs)
        cache_create = sum(r.get("cache_creation_in", 0) or 0 for r in rs)
        input_tok = sum(r.get("input_tokens", 0) or 0 for r in rs)
        # "hit ratio" = cached / (input + cache_read + cache_create)
        # — what fraction of the prompt tokens we paid less for.
        denom = input_tok + cache_read + cache_create
        ratio = cache_read / denom if denom > 0 else 0.0
        print(f"  {agent:<22} {len(rs):>6} {sys_label:>10} "
              f"{cache_read:>12} {cache_create:>14} {input_tok:>10} "
              f"{ratio:>9.1%}")
        totals["calls"] += len(rs)
        totals["cache_read"] += cache_read
        totals["cache_create"] += cache_create
        totals["input"] += input_tok
    denom_total = totals["input"] + totals["cache_read"] + totals["cache_create"]
    overall_ratio = totals["cache_read"] / denom_total if denom_total > 0 else 0.0
    print("  " + "-" * 90)
    print(f"  {'TOTAL':<22} {totals['calls']:>6} {'':>10} "
          f"{totals['cache_read']:>12} {totals['cache_create']:>14} "
          f"{totals['input']:>10} {overall_ratio:>9.1%}")
    print()

    # --- System-prompt size stability ---
    print("SYSTEM PROMPT SIZE STABILITY (one value per agent = Tier 1 working)")
    for agent in sorted(by_agent):
        sizes = sorted({r.get("system_bytes", 0) for r in by_agent[agent]})
        marker = "✓" if len(sizes) == 1 else "✗"
        print(f"  {marker} {agent:<22} sizes={sizes}")
    print()

    # --- Cross-experiment delta ---
    # For per-experiment roles, the cross-experiment cache hit is the
    # whole point of Tier 1. We can't easily detect "experiment
    # boundary" from the trace (it doesn't include experiment_id), but
    # we can look at sequential ordering of cache_read_in for the same
    # agent: a high value on the SECOND call within ~30 minutes (cache
    # TTL window) means the system-prompt prefix is being reused.
    print("CACHE BUILD-UP OVER SEQUENTIAL CALLS PER AGENT")
    print("  (cache_read_in growing from ~0 to a stable plateau means cache reuse")
    print("  is working; an unexpected drop back to 0 means something busted the")
    print("  cached prefix between calls — likely a system-prompt change.)")
    print()
    for agent in sorted(by_agent):
        rs = by_agent[agent]
        if len(rs) < 2:
            continue
        readings = [r.get("cache_read_in", 0) or 0 for r in rs]
        print(f"  {agent}: cache_read_in series = {readings}")
    print()

    # --- Conclusions ---
    if overall_ratio >= 0.50:
        print(f"  ✓ Overall cache hit ratio is {overall_ratio:.1%} (>=50%).")
        print("    The Tier 1 reorder + rec #2 + rec #3 fixes are delivering")
        print("    real cache reuse on the wire.")
    else:
        print(f"  ⚠ Overall cache hit ratio is only {overall_ratio:.1%}.")
        print("    Either the cache TTL is expiring between calls, the")
        print("    bundled CLI isn't applying cache_control, or a recent")
        print("    change re-busted the prefix. Investigate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
