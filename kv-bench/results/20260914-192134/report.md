# KV cache sweep

Every variant is a separate llama.cpp process (`-fa on -ngl 999`) run inside the model's own container.

## Prefill (tok/s)

| test | f16 | q4_0 | q8_0 |
|---|---|---|---|
| pp512 | 334.6 | 325.1 (-2.8%) | 256.0 (-23.5%) |
| pp2048 | 419.9 | 419.5 (-0.1%) | 420.3 (+0.1%) |
| pp8192 | 400.1 | 396.2 (-1.0%) | 393.7 (-1.6%) |

## Decode with the cache pre-filled to `depth` (tok/s)

`-n <tg> -d <depth>` prefills `depth` tokens, then decodes, so every pass reads a KV cache of that occupancy.

| test | f16 | q4_0 | q8_0 |
|---|---|---|---|
| tg64@1024 | 20.6 | 20.4 (-0.6%) | 20.6 (+0.3%) |
| tg64@4096 | 21.0 | 20.6 (-1.8%) | 20.8 (-0.8%) |
| tg64@16384 | 19.3 | 18.6 (-3.7%) | 19.0 (-1.6%) |

## Prefill + decode combined (tok/s)

| test | f16 | q4_0 | q8_0 |
|---|---|---|---|
| pp1024+tg128 | 136.8 | 135.7 (-0.8%) | 135.1 (-1.3%) |
| pp4096+tg128 | 261.5 | 261.1 (-0.1%) | 259.6 (-0.7%) |
| pp16384+tg128 | 330.5 | 328.6 (-0.6%) | 329.9 (-0.2%) |

## Quality

wikitext-2 subset (`kv-bench/data/ppl.txt`), identical corpus, seed and chunking for every variant. KL divergence compares each variant's logits with the baseline's saved logits; `Same top p` is the share of positions whose top token still matches at p=0.1.

| KV type | PPL | PPL ratio | KL mean | KL median | Same top p |
|---|---|---|---|---|---|
| f16 | 2.8392 | 1.0000 (baseline) | — | — | — |
| q4_0 | 2.8784 | 1.0139 | 0.04089 | 0.005520 | 93.71% |
| q8_0 | 2.8697 | 1.0109 | 0.02812 | 0.003401 | 94.80% |

