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

**`-ctkd`/`-ctvd` (the *draft* cache, used by speculative decoding) are a
different knob and the answer is no for a different reason: the MTP draft owns
1 of the 13 attention layers in play, so quantizing its cache is worth at most
0.36 GiB at 262 K context, costs 2-3 % speed and 1.7 pp of draft acceptance,
and provably never changes the output. The lever is enabling MTP at all:
+57 %. See Part 2.**

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
- `spec-bench.sh` — draft-cache sweep: one `llama-server` per variant + HTTP probe (`lib.sh` handles stop/restore)
- `spec-probe.py` — greedy `/v1/completions` driver; per-prompt tok/s, output hashes, `/metrics` scrape
- `data/ppl.txt` — 427-document wikitext-2-raw-v1/test excerpt (~300 KB)
- `results/<stamp>/` — raw `bench-*.{out,log}`, `ppl-*.{out,log}`, `STATUS`, `report.md`

---

# Part 2 — the draft cache: `-ctkd` / `-ctvd`

`-ctkd` / `--cache-type-k-draft` and `-ctvd` / `--cache-type-v-draft` (env
`LLAMA_ARG_SPEC_DRAFT_CACHE_TYPE_K` / `_V`) set the KV-cache type of the
**speculative-decoding draft model only**. The target cache — the 6 GiB one from
Part 1 — keeps whatever `-ctk`/`-ctv` say, so these flags answer a different
question: not "can I afford a longer context" but "can I make the drafter
cheaper". They are inert unless a drafter is configured (`-md` +
`--spec-type draft-mtp`, or `draft-simple`).

## Blocker: the image build cannot load any MTP head

llama.cpp in the image (b10950 `ad6c66839`) knows the `qwen4exp` arch and the
`nextn.*` MTP tensors (`grep -a -c nextn /usr/local/lib64/libllama.so.0` → 16),
but has no cross-model tensor borrowing (`borrow_shared` → 0). unsloth's heads
depend on borrowing: they ship 34 tensors (`blk.48.*`, i.e. one MTP block, plus
`token_embd` / `output` in the self-contained file) and take the rest from the
target. Both heads fail the same way:

| head (`MTP/`) | error |
|---|---|
| `mtp-…-shared-Q8_0.gguf` (2.60 GB, recommended) | `check_tensor_dims: tensor 'token_embd.weight' not found` |
| `mtp-…-Q8_0.gguf` (3.85 GB, self-contained) | `check_tensor_dims: tensor 'output_hc_norm.weight' not found` |

followed by `common_speculative_init_result: failed to load draft model` →
`srv llama_server: exiting due to model loading error`. And `llama-bench` has no
speculative-decoding flags, so on the image build the flags are untestable.

Fix, verified: unsloth's own release ships a **gfx1151 ROCm build**
(`app-b10909-mix-bea84f7-linux-x64-rocm-gfx1151.tar.gz`, build 10909
`329b6160f`, `borrow_shared` → 3). Extracted into the already-mounted HF cache
(`~/.cache/huggingface/llama-build/b10909-mix` → `/huggingface/llama-build/…`)
and started with `SPEC_SERVER`/`SPEC_LD`, the shared head loads in ~30 s and
drafts. The one remaining
`borrow_shared_tensor: this model is a draft head without its own
'token_embd.weight'; load it as a draft of its target model, not on its own`
comes from the extra-model memory-measurement pass, is expected by unsloth, and
is harmless — the real draft load right after it succeeds.

## Setup

| variant | draft flags |
|---|---|
| `none` | none (no `-md`, `--spec-type none`) — speed baseline |
| `f16` / `q8_0` / `q4_0` | `-md MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf --spec-type draft-mtp --spec-draft-n-max 2 -ctkd <t> -ctvd <t>` |

Identical otherwise, same binary for all four: `-ngl 999 -fa on --ctx-size
16384 --parallel 1 --no-warmup --metrics --temp 0 --presence-penalty 0
--repeat-penalty 1.0`. Client: 8 kind-tagged raw-completion prompts
(`data/spec-prompts.txt`), `--temp 0`, `ignore_eos`, `seed 42`, 192 tokens,
1 536 tokens per variant, one request in flight.

## Speed and acceptance

| variant | tok/s | vs none | token acceptance | drafts | mean len | output |
|---|---|---|---|---|---|---|
| none | 21.2 | baseline | — | 0 | — | `ce2499d964ed7844…` |
| f16 | 33.4 | **+57.1 %** | 77.49 % | 610 | 2.55 | `ce2499d964ed7844…` |
| q8_0 | 32.6 | +53.7 % | 76.86 % | 613 | 2.53 | `ce2499d964ed7844…` |
| q4_0 | 32.4 | +52.7 % | 75.83 % | 618 | 2.51 | `ce2499d964ed7844…` |

Per prompt (tok/s) — the MTP win is 1.1-1.6× depending on domain; the cache
type moves nothing beyond noise:

| prompt | none | f16 | q8_0 | q4_0 |
|---|---|---|---|---|
| code-python | 22.6 | 40.6 | 41.0 | 40.7 |
| code-rust | 22.4 | 38.3 | 37.5 | 38.8 |
| explain-c | 20.7 | 33.6 | 32.6 | 32.1 |
| structured-json | 21.1 | 35.2 | 35.1 | 34.9 |
| math | 20.4 | 29.0 | 26.1 | 27.1 |
| prose | 20.9 | 25.8 | 25.4 | 25.8 |
| ops-runbook | 21.1 | 31.1 | 30.5 | 29.2 |
| summarize | 20.6 | 33.3 | 32.8 | 30.7 |

Enabling MTP is the whole story (+57 %). The draft cache *type* is a net loss:
−2.4 % (q8_0) and −3.0 % (q4_0) against f16. The mechanism is visible in the
counters — a quantized draft cache degrades the draft's own attention reads, and
it hits the *later* draft position hardest, the one that reads deepest into that
cache:

| | drafts | accepted at pos 0 | pos 1 | token acceptance |
|---|---|---|---|---|
| f16 | 610 | 515 (84.4 %) | 428 (70.2 %) | 77.49 % |
| q8_0 | 613 | 513 (83.7 %) | 427 (69.7 %) | 76.86 % |
| q4_0 | 618 | 514 (83.2 %) | 421 (68.1 %) | 75.83 % |

`pos N` = share of drafts whose Nth token was accepted (`--spec-draft-n-max 2`);
`mean len` = tokens per decode step = 1 + accepted/drafts.

## Output identity

All four variants produced **byte-identical output**: `spec-<v>.txt` SHA-256
`ce2499d964ed7844…` (1 536 tokens each), and every per-prompt hash matches too.
That is not luck — `draft-mtp` verification is exact: the target re-evaluates
every drafted position and only accepts tokens matching its own greedy argmax,
so the draft cache can change *how many* tokens arrive per step, never *which*.
Measured at `--temp 0`; under sampling, llama.cpp's typical-acceptance path
preserves the distribution but the per-variant token streams are not what these
numbers describe.

## Memory — bounded by one attention layer

The draft is block 48 and nothing else: 1 attention layer, `head_count_kv=2`,
`key/value_length=256` → 1024 cache elements per token, versus the target's 12
full-attention layers → 12 288. Quantizing the draft cache therefore touches
1/13 of the KV memory that Part 1 was about:

| cache | f16 | q8_0 | q4_0 |
|---|---|---|---|
| target, 12 layers | 24.00 KiB/tok → 6.00 GiB @262 K | 12.75 → 3.19 | 6.75 → 1.69 |
| draft, 1 layer | 2.00 KiB/tok → 0.50 GiB @262 K | 1.06 → 0.27 | 0.56 → 0.14 |

Worst case `-ctkd q4_0 -ctvd q4_0` saves **0.36 GiB**: 6 % of the target cache,
0.4 % of the 93.7 GB of weights, for −3 % speed. The draft side of the table is
computed from the head's GGUF geometry (8.5 / 4.5 bits per value incl. block
scales) — `llama-server` prints no KV buffer size at default verbosity, and at
ctx 16384 the difference (32 vs 9 MiB) is far below free-memory noise.

## Verdict

- **Leave `-ctkd`/`-ctvd` alone.** They are a capacity knob for someone whose
  draft cache does not fit, and here it is 32 MiB at the sweep context. Default
  f16 is the fastest and the quality-neutral choice.
- **The lever is MTP itself: +57 % decode** (1.2-1.6× per domain, matching
  unsloth's 1.3-1.7× claim) with unchanged output. It does not run on the image
  build; to use it, switch the model service's binary to an unsloth
  `mix` release (`b10909-mix` verified here on gfx1151) or move to a build that
  carries `borrow_shared`. Until then the compose stack speculates not at all.
- `--spec-draft-n-max 2` is the right default. 70 % acceptance at position 1
  says position 3 still pays something; 4 probably not.
- Heads are *not* sidecar-discovered: `MTP/` is skipped, so `-md` must be
  explicit — that alone explains most "MTP does nothing" reports.
- These numbers are `-fa on`, like Part 1; production runs `FLASH_ATTN: auto`
  and `--parallel` >1, so re-measure before quoting them for the live service.

## Reproducing Part 2

```sh
mkdir -p ~/.cache/huggingface/llama-build/b10909-mix
curl -L -o /tmp/u.tar.gz https://github.com/unslothai/llama.cpp/releases/download/b10909-mix-bea84f7/app-b10909-mix-bea84f7-linux-x64-rocm-gfx1151.tar.gz
tar xzf /tmp/u.tar.gz -C ~/.cache/huggingface/llama-build/b10909-mix

SPEC_SERVER=/huggingface/llama-build/b10909-mix/llama-server \
SPEC_LD=/huggingface/llama-build/b10909-mix ./kv-bench/spec-bench.sh
```

Knobs: `SPEC_VARIANTS SPEC_SERVER SPEC_LD SPEC_DRAFT SPEC_CTX SPEC_NMAX
SPEC_TOKENS SPEC_PORT SPEC_STOP SPEC_LIMIT`. Raw output in
`results/<stamp>/spec-<v>.{json,txt,metrics,log}`; the numbers above are
`results/20260915-031541`.
