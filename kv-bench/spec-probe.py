#!/usr/bin/env python3
"""Measure one llama-server instance: decode throughput, output identity, spec stats.

    kv-bench/spec-probe.py --url http://127.0.0.1:9161 --label f16 --out results/<stamp>/spec-f16

Sends every prompt in kv-bench/data/spec-prompts.txt to /v1/completions with
temperature 0 and ignore_eos, one request in flight at a time (speculative
decoding gains are a low-concurrency effect), and writes:

    <out>.json      per-prompt tokens/s, prompt/completion counts, output hash
    <out>.txt       the generated text, delimited -- diff these across variants
                    to see whether the draft cache changed what was generated
    <out>.metrics   raw Prometheus scrape, for the spec/draft counters

Requests are measured twice: a warmup pass (discarded) so the draft graph is
built and the prompt cache is populated, then the timed pass.
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request

PROMPTS = re.compile(r"^# kind: (\S+)\s*$")


def load_prompts(path):
    items, kind, buf = [], None, []
    for line in open(path, encoding="utf-8"):
        m = PROMPTS.match(line)
        if m:
            if kind is not None:
                items.append((kind, "".join(buf).strip()))
            kind, buf = m.group(1), []
        elif kind is not None:
            buf.append(line)
    if kind is not None:
        items.append((kind, "".join(buf).strip()))
    if not items:
        sys.exit(f"no '# kind: <name>' records in {path}")
    return items


def post(url, payload, timeout):
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prompts", default=str(__import__("pathlib").Path(__file__).parent / "data" / "spec-prompts.txt"))
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--limit", type=int, default=0, help="only the first N prompts (smoke runs)")
    ap.add_argument("--tokens", type=int, default=192, help="max_tokens per request")
    a = ap.parse_args()

    items = load_prompts(a.prompts)
    if a.limit:
        items = items[: a.limit]
    body = {"temperature": 0, "max_tokens": a.tokens, "ignore_eos": True,
            "seed": 42, "stream": False}

    # warmup: build the draft graph / compile kernels, and warm the page cache
    for kind, prompt in items[:2]:
        post(a.url, dict(body, model=a.label, prompt=prompt, max_tokens=16), a.timeout)

    rows, texts = [], []
    for kind, prompt in items:
        t0 = time.perf_counter()
        r = post(a.url, dict(body, model=a.label, prompt=prompt), a.timeout)
        wall = time.perf_counter() - t0
        text = (r.get("choices") or [{}])[0].get("text", "")
        usage = r.get("usage") or {}
        n = usage.get("completion_tokens") or len(text)
        rows.append({
            "kind": kind,
            "seconds": round(wall, 3),
            "completion_tokens": n,
            "prompt_tokens": usage.get("prompt_tokens"),
            "tok_per_s": round(n / wall, 2) if wall > 0 else None,
            "sha256": hashlib.sha256(text.encode()).hexdigest()[:16],
        })
        texts.append((kind, text))
        print(f"  {kind:18} {rows[-1]['tok_per_s']:6.2f} tok/s  {n:4d} tok  {rows[-1]['sha256']}",
              file=sys.stderr)

    mean = sum(r["tok_per_s"] for r in rows) / len(rows)
    total_tok = sum(r["completion_tokens"] for r in rows)
    total_sec = sum(r["seconds"] for r in rows)

    with open(a.out + ".txt", "w", encoding="utf-8") as f:
        for kind, text in texts:
            f.write(f"===== {kind} =====\n{text}\n")

    try:
        with urllib.request.urlopen(a.url.rstrip("/") + "/metrics", timeout=30) as r:
            open(a.out + ".metrics", "w").write(r.read().decode())
    except Exception as e:  # metrics are optional; the run is still valid
        print(f"  metrics unavailable: {e}", file=sys.stderr)

    summary = {
        "label": a.label,
        "url": a.url,
        "requests": rows,
        "mean_tok_per_s": round(mean, 2),
        # overall weights long generations, matching how a user waits
        "overall_tok_per_s": round(total_tok / total_sec, 2) if total_sec else None,
        "total_completion_tokens": total_tok,
        "output_sha256": hashlib.sha256("\n".join(t for _, t in texts).encode()).hexdigest()[:16],
    }
    json.dump(summary, open(a.out + ".json", "w"), indent=2)
    print(f"{a.label}: mean {mean:.2f} tok/s, overall {total_tok / total_sec:.2f} tok/s, "
          f"output sha {summary['output_sha256']} ({len(rows)} greedy generations)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
