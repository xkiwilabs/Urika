#!/usr/bin/env python3
"""Summarize a URIKA_PROMPT_TRACE_FILE JSONL into a per-agent table.

Usage:
    python dev/scripts/analyze_prompt_trace.py /tmp/urika-trace-co2.jsonl
    cat trace.jsonl | python dev/scripts/analyze_prompt_trace.py

The trace file is produced by ``ClaudeSDKRunner.run`` when the
``URIKA_PROMPT_TRACE_FILE`` environment variable is set (v0.4.1+).
Each line is a JSON record with the fields:
    ts, agent, model, system_bytes, prompt_bytes,
    tokens_in_total, input_tokens, cache_creation_in,
    cache_read_in, tokens_out, duration_ms, success

This script is the analysis side of that instrumentation: it groups
calls by agent and reports the distributions that matter for
prompt-bloat decisions — namely cache-hit ratio (which determines
whether trimming the system prompt actually saves tokens) and the
fresh-input + output token counts (which is what the API actually
bills you for per call).

Outputs a per-agent table plus an overall summary. No third-party
dependencies — stdlib only.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


_FIELDS = (
    "system_bytes",
    "prompt_bytes",
    "input_tokens",
    "cache_creation_in",
    "cache_read_in",
    "tokens_out",
    "duration_ms",
)


def _percentile(values: list[float], p: float) -> float:
    """Naive percentile helper — fine for trace files of a few thousand
    records. ``statistics.quantiles`` exists but is awkward for a single
    value; this is clearer.
    """
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def _cache_hit_ratio(record: dict) -> float:
    """Return cache_read / (cache_read + cache_creation + input_tokens).

    A ratio close to 1.0 means the SDK's prompt cache is doing the
    work and the system_prompt + tool list have already been
    amortised. A ratio close to 0 means every call is paying full
    input-token cost.
    """
    total = (
        record.get("cache_read_in", 0)
        + record.get("cache_creation_in", 0)
        + record.get("input_tokens", 0)
    )
    if total == 0:
        return 0.0
    return record.get("cache_read_in", 0) / total


def _load(path: Path | None) -> list[dict]:
    if path is None:
        text = sys.stdin.read()
    else:
        text = path.read_text(encoding="utf-8")
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"warning: skipping malformed line: {exc}", file=sys.stderr)
    return out


def _summarize(records: list[dict]) -> None:
    if not records:
        print("No records found.", file=sys.stderr)
        sys.exit(1)

    by_agent: dict[str, list[dict]] = {}
    for r in records:
        by_agent.setdefault(r.get("agent", "?"), []).append(r)

    # Per-agent table
    header = (
        f"{'agent':<22s} {'n':>3s} "
        f"{'sys_KB':>7s} {'prompt_KB_avg':>14s} {'prompt_KB_max':>14s} "
        f"{'in_avg':>7s} {'cache_read_avg':>15s} {'cache_hit%':>11s} "
        f"{'out_avg':>8s} {'sec_avg':>8s} {'sec_p95':>8s}"
    )
    print(header)
    print("-" * len(header))

    overall_records = []
    for agent in sorted(by_agent):
        recs = by_agent[agent]
        overall_records.extend(recs)
        prompts = [r["prompt_bytes"] for r in recs]
        sys_bytes = [r["system_bytes"] for r in recs]
        ins = [r["input_tokens"] for r in recs]
        cache_reads = [r["cache_read_in"] for r in recs]
        outs = [r["tokens_out"] for r in recs]
        durs = [r["duration_ms"] / 1000 for r in recs]
        hit_ratios = [_cache_hit_ratio(r) for r in recs]

        print(
            f"{agent:<22s} {len(recs):>3d} "
            f"{statistics.mean(sys_bytes) / 1024:>7.1f} "
            f"{statistics.mean(prompts) / 1024:>14.2f} "
            f"{max(prompts) / 1024:>14.2f} "
            f"{statistics.mean(ins):>7.0f} "
            f"{statistics.mean(cache_reads):>15.0f} "
            f"{100 * statistics.mean(hit_ratios):>10.1f}% "
            f"{statistics.mean(outs):>8.0f} "
            f"{statistics.mean(durs):>8.1f} "
            f"{_percentile(durs, 0.95):>8.1f}"
        )

    # Overall totals
    print()
    print("Overall:")
    total_in = sum(r["input_tokens"] for r in overall_records)
    total_cr = sum(r["cache_read_in"] for r in overall_records)
    total_cc = sum(r["cache_creation_in"] for r in overall_records)
    total_out = sum(r["tokens_out"] for r in overall_records)
    total_sec = sum(r["duration_ms"] for r in overall_records) / 1000
    grand_total_in = total_in + total_cr + total_cc
    print(f"  calls:                {len(overall_records)}")
    print(f"  fresh input tokens:   {total_in:>12,d}")
    print(f"  cache_creation in:    {total_cc:>12,d}")
    print(f"  cache_read in:        {total_cr:>12,d}")
    print(
        "  cache hit ratio:      "
        f"{100 * total_cr / grand_total_in if grand_total_in else 0:>11.1f}%"
    )
    print(f"  output tokens:        {total_out:>12,d}")
    print(f"  total wall seconds:   {total_sec:>12,.1f}")
    failed = sum(1 for r in overall_records if not r.get("success"))
    if failed:
        print(f"  failed calls:         {failed:>12d}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        return
    path = Path(args[0]) if args else None
    if path is not None and not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        sys.exit(2)
    records = _load(path)
    _summarize(records)


if __name__ == "__main__":
    main()
