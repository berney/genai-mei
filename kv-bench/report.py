#!/usr/bin/env python3
"""Summarize kv-bench sweep output into markdown.

    ./kv-bench/report.py kv-bench/results/<stamp> [more-dirs...]

Merges every bench-<variant>.out (llama-bench -o jsonl) and ppl-<variant>.out
/ .log (llama-perplexity) found in the given directories, so a follow-up run
-- e.g. the decode-at-depth pass -- folds into the first sweep's table.
Writes report.md into the first directory.
"""

import json
import re
import sys
from pathlib import Path

PPL_FINAL = re.compile(r"Final estimate: PPL = ([0-9.]+) \+/- ([0-9.]+)")
PPL_Q = re.compile(r"Mean PPL\(Q\)\s*:\s*([0-9.]+)\s*±\s*([0-9.]+)")
PPL_RATIO = re.compile(r"Mean PPL\(Q\)/PPL\(base\)\s*:\s*([0-9.]+)")
KLD_MEAN = re.compile(r"Mean\s+KLD:\s*([0-9.]+)\s*±\s*([0-9.]+)")
KLD_MEDIAN = re.compile(r"Median\s+KLD:\s*([0-9.]+)")
SAME_TOP = re.compile(r"Same top p:\s*([0-9.]+)")


def bench_rows(path: Path):
    """llama-bench jsonl rows; tolerate a truncated run or a -o json array."""
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "avg_ts" in row:
            rows.append(row)
    return rows


def label(row):
    pp, gen, depth = row.get("n_prompt", 0), row.get("n_gen", 0), row.get("n_depth", 0)
    if gen and not pp:
        return f"tg{gen}@{depth}" if depth else f"tg{gen}"
    if gen:
        return f"pp{pp}+tg{gen}"
    return f"pp{pp}"


def mean_ts(row):
    samples = row.get("samples_ts") or [row["avg_ts"]]
    return sum(samples) / len(samples)


def quality(variant: str, roots):
    """PPL from the baseline run; PPL ratio + KL deltas from the others."""
    info = {}
    for d in roots:
        text = ""
        for name in (f"ppl-{variant}.out", f"ppl-{variant}.log"):
            p = d / name
            if p.exists():
                text += p.read_text(errors="replace")
        if not text:
            continue
        for regex, key in ((PPL_FINAL, "ppl"), (PPL_Q, "ppl"), (PPL_RATIO, "ratio"),
                           (KLD_MEAN, "kld"), (KLD_MEDIAN, "kld_med"), (SAME_TOP, "same_top")):
            m = regex.search(text)
            if m and key not in info:
                info[key] = float(m.group(1))
    return info


def main(dirs):
    roots = []
    for d in dirs:
        p = Path(d)
        if not p.is_dir():
            sys.exit(f"not a directory: {p}")
        roots.append(p)

    variants, speed = [], {}
    for root in roots:
        for f in sorted(root.glob("bench-*.out")):
            v = f.stem[len("bench-"):]
            if v not in speed:
                variants.append(v)
                speed[v] = {}
            for row in bench_rows(f):
                speed[v][label(row)] = mean_ts(row)

    if not variants:
        sys.exit(f"no bench-*.out in {roots[0]}")
    if "f16" in variants:  # baseline first
        variants.insert(0, variants.pop(variants.index("f16")))

    tests = {}
    for v in variants:
        for name, ts in speed[v].items():
            tests.setdefault(name, {})[v] = ts

    lines = ["# KV cache sweep", "",
             "Every variant is a separate llama.cpp process (`-fa on -ngl 999`) run "
             "inside the model's own container.", ""]

    def table(title, names, note=""):
        lines.append(f"## {title}")
        lines.append("")
        if note:
            lines.extend([note, ""])
        lines.extend(["| test | " + " | ".join(variants) + " |", "|" + "---|" * (len(variants) + 1)])
        for name in names:
            cells = []
            for v in variants:
                ts = tests.get(name, {}).get(v)
                base = tests.get(name, {}).get(variants[0])
                if ts is None:
                    cells.append("—")
                elif v == variants[0] or not base:
                    cells.append(f"{ts:.1f}")
                else:
                    cells.append(f"{ts:.1f} ({(ts / base - 1) * 100:+.1f}%)")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        lines.append("")

    num = lambda t: int(re.search(r"\d+", t).group())
    pp_tests = sorted([t for t in tests if t.startswith("pp") and "+" not in t], key=num)
    tg_tests = sorted([t for t in tests if t.startswith("tg")], key=num)
    pg_tests = sorted([t for t in tests if "+" in t], key=num)

    table("Prefill (tok/s)", pp_tests)
    table("Decode with the cache pre-filled to `depth` (tok/s)", tg_tests,
          "`-n <tg> -d <depth>` prefills `depth` tokens, then decodes, so every pass "
          "reads a KV cache of that occupancy.")
    table("Prefill + decode combined (tok/s)", pg_tests)

    quals = {v: quality(v, roots) for v in variants}
    if any(quals.values()):
        lines += ["## Quality", "",
                  "wikitext-2 subset (`kv-bench/data/ppl.txt`), identical corpus, seed and "
                  "chunking for every variant. KL divergence compares each variant's logits "
                  "with the baseline's saved logits; `Same top p` is the share of positions "
                  "whose top token still matches at p=0.1.", ""]
        lines += ["| KV type | PPL | PPL ratio | KL mean | KL median | Same top p |",
                  "|---|---|---|---|---|---|"]
        for v in variants:
            q = quals[v]
            ppl, ratio = q.get("ppl"), q.get("ratio")
            if ratio is None and ppl is not None:
                ratio = 1.0
            cells = [
                "—" if ppl is None else f"{ppl:.4f}",
                "—" if ratio is None else f"{ratio:.4f}" + (" (baseline)" if ratio == 1.0 else ""),
                "—" if "kld" not in q else f"{q['kld']:.5f}",
                "—" if "kld_med" not in q else f"{q['kld_med']:.6f}",
                "—" if "same_top" not in q else f"{q['same_top']:.2f}%",
            ]
            lines.append("| " + v + " | " + " | ".join(cells) + " |")
        lines.append("")

    text = "\n".join(lines)
    (roots[0] / "report.md").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
