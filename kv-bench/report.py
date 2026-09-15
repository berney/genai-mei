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


SPEC_ORDER = ["none", "f16", "q8_0", "q4_0"]
SPEC_DRAFTS = "llamacpp:spec_decode_num_drafts_total"
SPEC_DTOK = "llamacpp:spec_decode_num_draft_tokens_total"
SPEC_ACC = "llamacpp:spec_decode_num_accepted_tokens_total"


def metric_sum(path: Path, name):
    """Sum a Prometheus counter across its label series."""
    total = None
    if not path.exists():
        return None
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("#") or " " not in line:
            continue
        key, _, val = line.rpartition(" ")
        if key.split("{", 1)[0] != name:
            continue
        try:
            total = (total or 0.0) + float(val)
        except ValueError:
            pass
    return total


def spec_rows(roots):
    """One row per spec-<variant>.json produced by spec-bench.sh."""
    rows, seen = [], set()
    for root in roots:
        for f in sorted(root.glob("spec-*.json")):
            v = f.stem[len("spec-"):]
            if v in seen:
                continue
            seen.add(v)
            try:
                data = json.loads(f.read_text())
            except ValueError:
                continue
            mf = root / f"spec-{v}.metrics"
            drafts = metric_sum(mf, SPEC_DRAFTS) or 0.0
            dtok = metric_sum(mf, SPEC_DTOK) or 0.0
            acc = metric_sum(mf, SPEC_ACC) or 0.0
            rows.append({
                "v": v,
                "tps": data.get("mean_tok_per_s"),
                "out": data.get("output_sha256", ""),
                "drafts": drafts,
                "accept": acc / dtok if dtok else None,
                # each draft step always contributes the verified token too
                "mean_len": (acc + drafts) / drafts if drafts else None,
                "per": {r["kind"]: r for r in data.get("requests", [])},
            })
    rows.sort(key=lambda r: SPEC_ORDER.index(r["v"]) if r["v"] in SPEC_ORDER else len(SPEC_ORDER))
    return rows


def spec_lines(rows):
    base = next((r for r in rows if r["v"] == "none"), rows[0])
    out = ["# Speculative decoding: draft KV cache (`-ctkd` / `-ctvd`)", "",
           "`--spec-type draft-mtp` with an MTP head; `-ctkd`/`-ctvd` set the draft "
           "cache type, the target cache stays f16. Greedy `--temp 0` requests with "
           "`ignore_eos`, one server per variant. Acceptance = accepted / drafted "
           "tokens; mean len = tokens per decode step (1 + accepted per draft).", ""]
    out += ["| variant | tok/s | vs " + base["v"] + " | acceptance | drafts | mean len | output |",
            "|---|---|---|---|---|---|---|"]
    for r in rows:
        rel = "—"
        if r is not base and base["tps"] and r["tps"]:
            rel = f"{(r['tps'] / base['tps'] - 1) * 100:+.1f}%"
        if r is base:
            rel = "baseline" + ("" if r["v"] == "none" else " (draft f16)")
        note = "—"
        if r is not base and base["out"]:
            note = "identical to " + base["v"] if r["out"] == base["out"] \
                else "**differs from " + base["v"] + "**"
        out.append("| {} | {} | {} | {} | {} | {} | `{}` {} |".format(
            r["v"],
            "—" if r["tps"] is None else f"{r['tps']:.1f}",
            rel,
            "—" if r["accept"] is None else f"{r['accept'] * 100:.2f}%",
            f"{r['drafts']:.0f}",
            "—" if r["mean_len"] is None else f"{r['mean_len']:.2f}",
            str(r["out"])[:16], note))
    out.append("")
    dead = [r["v"] for r in rows if r["v"] != "none" and not r["drafts"]]
    if dead:
        out += [f"**Warning: no drafts counted for {', '.join(dead)} -- speculation did not run.**", ""]

    kinds = []
    for r in rows:
        for k in r["per"]:
            if k not in kinds:
                kinds.append(k)
    if kinds:
        out += ["## Per-prompt decode speed (tok/s)", "",
                "| prompt | " + " | ".join(r["v"] for r in rows) + " |",
                "|---|" + "---|" * len(rows)]
        for k in kinds:
            out.append("| {} | {} |".format(
                k, " | ".join("—" if k not in r["per"] else f"{r['per'][k]['tok_per_s']:.1f}"
                              for r in rows)))
        out.append("")
    return out


def main(dirs):
    roots = []
    for d in dirs:
        p = Path(d)
        if not p.is_dir():
            sys.exit(f"not a directory: {p}")
        roots.append(p)

    spec = spec_rows(roots)
    if spec and not any(any(r.glob("bench-*.out")) for r in roots):
        text = "\n".join(spec_lines(spec))
        (roots[0] / "report.md").write_text(text + "\n")
        print(text)
        return

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
