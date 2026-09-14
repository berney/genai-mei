# kv-bench — does KV-cache quantization pay off on this box?

Measured on the Framework Desktop (Ryzen AI MAX+ 395 / gfx1151, 124 GiB unified)
against the compose service `qwen3.8-Flash-Next-IQ4`
(`Qwen3.8-Flash-Next-UD-IQ4_XS`, arch `qwen4exp`, llama.cpp
`0.4.0-dev` b10950 `ad6c66839`, ROCm).

## Short answer

**No. KV-cache quantization makes this model measurably worse and buys no
throughput. Keep the f16 cache** — which is what `llama-swap.yaml` already
does. Reach for `q8_0` only when a single slot genuinely needs >2× the context
window and a 1.1 % perplexity regression is acceptable; treat `q4_0` as
quality-unsafe.

## Speed — `llama-bench`, `-ngl 999 -fa on`, 2 reps, `--no-warmup`

| test | f16 | q8_0 | q4_0 |
|---|---|---|---|
| pp2048 | 419.9 | 420.3 (+0.1 %) | 419.5 (−0.1 %) |
| pp8192 | 400.1 | 393.7 (−1.6 %) | 396.2 (−1.0 %) |
| tg64 @ depth 1024 | 20.6 | 20.6 (+0.3 %) | 20.4 (−0.6 %) |
| tg64 @ depth 4096 | 21.0 | 20.8 (−0.8 %) | 20.6 (−1.8 %) |
| tg64 @ depth 16384 | 19.3 | 19.0 (−1.6 %) | 18.6 (−3.7 %) |
| pp16384+tg128 | 330.5 | 329.9 (−0.2 %) | 328.6 (−0.6 %) |

`pp512` once showed −23.5 % for `q8_0`: noise. Sample stddev there is 45–69
tok/s for *every* variant and the second repetitions are 300.9 / 304.5 / 293.3.
Quantized cache is never faster; at 16 K depth it costs 1.6–3.7 % (dequant on
the attention path).

**Why there is nothing to win** (`./kv-bench/kv-size.py`, from the GGUF header):
`qwen4exp` has 48 blocks but **only 12 carry a KV cache** — 36 of them are
Gated DeltaNet layers whose recurrent state is unaffected by `-ctk/-ctv`. QSA
sparse attention then caps a decode step at `attention.indexer.top_k = 2048`
cached entries per layer, i.e. **3 MiB/token = 0.06 GiB/s** at 20 tok/s, against
roughly 30 GiB/s of IQ4_XS MoE weight traffic. The KV cache is ~0.2 % of decode
bandwidth on this architecture.

## Quality — `llama-perplexity`, wikitext-2 subset (24 576 tokens)

Identical corpus, seed and chunking per variant. KL divergence compares each
variant's logits against the f16 baseline's saved logits.

| KV | PPL | ratio | KL mean | KL median | same top-p token |
|---|---|---|---|---|---|
| f16 | 2.8392 | 1.0000 (base) | — | — | — |
| q8_0 | 2.8697 | **1.0109 ± 0.0028** | 0.02812 | 0.003401 | **94.80 %** |
| q4_0 | 2.8784 | 1.0139 | 0.04089 | 0.005520 | 93.71 % |

ΔPPL for `q8_0` is `+0.0308 ± 0.0079` — 3.9σ, i.e. real. The KL median (0.0034)
says most positions are untouched; the tail is not (max KL 8.33, 99.9th pct
1.30). `Same top p` answers "which tokens get generated": **1 in 20 positions
already picks a different token at p = 0.1** with `q8_0`, and that compounds
across a long generation. Flash attention requires matched K/V types
(`FA_QUANTS = q4_0-q4_0,q8_0-q8_0,f16-f16`), so cheap-K-with-expensive-V is not
an option.

## Memory — the only real argument, and it needs ~128 K+ contexts

24.00 KiB/token f16 → 6.00 GiB at 262 144 tokens; `q8_0` 3.19 GiB (53 %),
`q4_0` 1.69 GiB (28 %). With the production `n_ctx_slot=262144` and 4 slots that
is at most ~4 GiB saved out of a 124 GiB unified pool holding a 93.7 GB model.

## Caveats

One model, one corpus (wikitext-2), 2 repetitions, no warmup, `-fa on`
(production uses `auto`). The PPL ratio is tight (±0.28 %) but perplexity does
not capture task quality on code or long-context reasoning.

## Reproducing

    ./kv-bench/sweep.sh qwen3.8-Flash-Next-IQ4
    KV_PG= KV_PP=0 KV_TG=64 KV_DEPTH=1024,4096,16384 KV_PPL=0 ./kv-bench/sweep.sh
    ./kv-bench/report.py kv-bench/results/<stamp-1> kv-bench/results/<stamp-2>

`sweep.sh` stops `llama-swap`, the model service and `comfyui` for the duration
(quantized-cache runs cannot coexist with the loaded model on this box) and
restores + health-checks them on exit via `trap`, including on failure. Knobs:
`KV_VARIANTS KV_PP KV_TG KV_DEPTH KV_PG KV_PPL KV_CHUNKS KV_REPS KV_STOP
KV_DEADLINE KV_KEEP_LOGITS`. The 6 GB baseline logit dump is deleted at the end
unless `KV_KEEP_LOGITS=1`.

## Files

- `sweep.sh` — orchestrator (llama-bench + llama-perplexity, per-variant processes)
- `report.py` — merges one or more result dirs into `report.md`
- `kv-size.py` — KV memory math + QSA decode-read estimate from the GGUF header
- `data/ppl.txt` — 427-document wikitext-2-raw-v1/test excerpt (~300 KB)
- `results/<stamp>/` — raw `bench-*.{out,log}`, `ppl-*.{out,log}`, `STATUS`, `report.md`
