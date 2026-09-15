# Speculative decoding: draft KV cache (`-ctkd` / `-ctvd`)

`--spec-type draft-mtp` with an MTP head; `-ctkd`/`-ctvd` set the draft cache type, the target cache stays f16. Greedy `--temp 0` requests with `ignore_eos`, one server per variant. Acceptance = accepted / drafted tokens; mean len = tokens per decode step (1 + accepted per draft).

| variant | tok/s | vs none | acceptance | drafts | mean len | output |
|---|---|---|---|---|---|---|
| none | 21.2 | baseline | — | 0 | — | `461ca1d809ae1ea0` — |
| f16 | 33.4 | +57.1% | 77.49% | 610 | 2.55 | `461ca1d809ae1ea0` identical to none |
| q8_0 | 32.6 | +53.7% | 76.86% | 613 | 2.53 | `461ca1d809ae1ea0` identical to none |
| q4_0 | 32.4 | +52.7% | 75.83% | 618 | 2.51 | `461ca1d809ae1ea0` identical to none |

## Per-prompt decode speed (tok/s)

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

