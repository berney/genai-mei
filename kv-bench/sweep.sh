#!/bin/sh
#
# KV-cache quantization sweep for a compose-hosted llama.cpp model.
#
#   ./kv-bench/sweep.sh [service]
#
# For every cache-type variant it runs, inside the model's own container
# (--entrypoint override, so mounts/env/DNS come from docker-compose.yml):
#
#   llama-bench         pp+tg combined tests: prefill/decode tok/s at
#                       1k/4k/16k token contexts   -> results/bench-<v>.jsonl
#   llama-perplexity    PPL over data/ppl.txt, plus KL divergence of the
#                       logits against the f16 baseline -> results/ppl-<v>.log
#
# Variables:
#   KV_VARIANTS  space separated K=V cache types (default: "f16 q8_0 q4_0")
#                f16 must be listed first: it is the PPL/KL baseline.
#   KV_STOP      1 (default) stops llama-swap + the model service for the run
#                so nothing contends for memory; services are restored and
#                health-checked on exit, even on failure. 0 = leave running.
#   KV_PP        comma list of pure-prefill sizes   (default: "512,2048,8192")
#   KV_TG        decode-only size (use with KV_DEPTH) (default: 0)
#   KV_DEPTH     KV depth for decode-only tests      (default: 0)
#   KV_PG        repeated -pg flags, pp,tg pairs    (default: "-pg 1024,128 -pg 4096,128 -pg 16384,128")
#   KV_PPL       0 skips llama-perplexity (bench-only run) (default: 1)
#   KV_CHUNKS    llama-perplexity chunk count (default: 3)
#   KV_REPS      llama-bench repetitions (default: 2)
#
set -eu

KV_SERVICE="${1:-qwen3.8-Flash-Next-IQ4}"
KV_VARIANTS="${KV_VARIANTS:-f16 q8_0 q4_0}"
KV_STOP="${KV_STOP:-1}"
KV_CTX="${KV_CTX:-8192}"
KV_CHUNKS="${KV_CHUNKS:-3}"
KV_PP="${KV_PP:-512,2048,8192}"
KV_TG="${KV_TG:-0}"
KV_DEPTH="${KV_DEPTH:-0}"
# (no colon: KV_PG= explicitly empty means "no -pg tests", e.g. decode-only runs)
KV_PG="${KV_PG--pg 1024,128 -pg 4096,128 -pg 16384,128}"
KV_PPL="${KV_PPL:-1}"
KV_REPS="${KV_REPS:-2}"

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/kv-bench/results/$(date +%Y%m%d-%H%M%S)"
START=$(date +%s)
BASELINE=$(echo "$KV_VARIANTS" | cut -d' ' -f1)
LOGITS="/out/logits-baseline.bin"

export PODMAN_COMPOSE_WARNING_LOGS=false
mkdir -p "$OUT"

# llama.cpp tools do not read LLAMA_ARG_* env vars for the model path.
MODEL=$(docker compose run --rm --no-deps -T --entrypoint printenv "$KV_SERVICE" LLAMA_ARG_MODEL 2>/dev/null | tail -1)
[ -n "$MODEL" ] || { echo "could not resolve LLAMA_ARG_MODEL for $KV_SERVICE" >&2; exit 1; }

status() { echo "$*" | tee -a "$OUT/STATUS"; echo; }

RESTORED=0
STOPPED=""
restore() {
    rc=$?
    [ "$RESTORED" = 1 ] && return
    RESTORED=1
    if [ -n "$STOPPED" ]; then
        status "restoring: $STOPPED"
        # model first, then the swap proxy, so llama-swap finds it warm
        for s in $STOPPED; do
            docker compose up -d "$s" >>"$OUT/restore.log" 2>&1 || status "FAILED to start $s"
        done
        # `docker compose port` prints "0.0.0.0:8160" -- keep the port only
        model_port=$(docker compose port "$KV_SERVICE" 8080 2>/dev/null | head -1)
        model_port=${model_port##*:}
        [ -n "$model_port" ] || model_port=8160
        i=0
        until curl -sf "http://localhost:${model_port}/health" >/dev/null 2>&1; do
            i=$((i + 1))
            if [ "$i" -gt 300 ]; then
                status "TIMEOUT waiting for $KV_SERVICE health on :$model_port"
                break
            fi
            sleep 2
        done
        [ "$i" -le 300 ] && status "$KV_SERVICE healthy on :$model_port after $((i * 2))s"
        if docker compose ps --services 2>/dev/null | grep -qx llama-swap; then
            curl -sf "http://localhost:8090/v1/models" >/dev/null 2>&1 \
                && status "llama-swap reachable on :8090" \
                || status "WARNING llama-swap /v1/models not answering"
        fi
    fi
    exit $rc
}
trap restore EXIT INT TERM

status "service: $KV_SERVICE"
status "model:   $MODEL"
status "variants: $KV_VARIANTS (baseline $BASELINE) pp='$KV_PP' tg=$KV_TG depth=$KV_DEPTH pg='$KV_PG' reps=$KV_REPS ppl=$KV_PPL ctx=$KV_CTX chunks=$KV_CHUNKS"

if [ "$KV_STOP" = 1 ]; then
    STOPPED=$(docker compose ps --services 2>/dev/null | grep -E "^(llama-swap|${KV_SERVICE}|comfyui)$" | tr '\n' ' ')
    if [ -n "$STOPPED" ]; then
        # llama-swap first: while it runs it will respawn the model on request
        status "stopping: $STOPPED"
        docker compose stop llama-swap "$KV_SERVICE" comfyui >>"$OUT/stop.log" 2>&1 || true
        sleep 5
    else
        STOPPED=""
    fi
fi

free_mem() { free -h | awk '/^Mem:/ {print $3 " used, " $4 " free (avail " $7 ")"}'; }
status "memory: $(free_mem)"

run() {
    # run <name> <entrypoint> <args...>
    name=$1; entry=$2; shift 2
    elapsed=$(( $(date +%s) - START ))
    if [ "$elapsed" -gt "$KV_DEADLINE" ]; then
        status "SKIP $name (deadline ${KV_DEADLINE}s reached)"
        return 0
    fi
    status "== $name (${elapsed}s elapsed)"
    set -- -m "$MODEL" "$@"
    if docker compose run --rm --no-deps -T \
        -e GGML_VERBOSE=0 -e ROCBLAS_LAYER=0 -e HSA_ENABLE_SDMA=0 \
        -v "$OUT:/out" -v "$ROOT/kv-bench/data:/data:ro" \
        --entrypoint "$entry" "$KV_SERVICE" "$@" \
        >"$OUT/$name.out" 2>"$OUT/$name.log"; then
        status "ok   $name  $(free_mem)"
    else
        rc=$?
        status "FAIL $name (exit $rc) -- see $name.log"
        tail -5 "$OUT/$name.log" | tee -a "$OUT/STATUS"
        return $rc
    fi
}

for v in $KV_VARIANTS; do
    # 1. speed: combined pp+tg so decode is measured with the KV cache filled
    if ! run "bench-$v" llama-bench \
        -ngl 999 -fa on -ctk "$v" -ctv "$v" -p "$KV_PP" -n "$KV_TG" -d "$KV_DEPTH" \
        $KV_PG -r "$KV_REPS" --no-warmup -o jsonl; then
        status "skipping remaining steps for $v (bench failed: KV type likely unsupported)"
        continue
    fi

    # 2. quality: PPL, and KL divergence against the baseline logits
    if [ "$KV_PPL" = 1 ]; then
        nppl=$(echo "$KV_VARIANTS" | wc -w)
        if [ "$v" = "$BASELINE" ]; then
            # the baseline logits are only worth 6 GB if something compares to them
            [ "$nppl" -gt 1 ] && ppl_extra="--save-all-logits $LOGITS"
        else
            ppl_extra="--kl-divergence --kl-divergence-base $LOGITS"
        fi
        # shellcheck disable=SC2086
        run "ppl-$v" llama-perplexity \
            -ngl 999 -fa on -ctk "$v" -ctv "$v" \
            -c "$KV_CTX" -b 2048 -ub 512 --chunks "$KV_CHUNKS" \
            -f /data/ppl.txt -s 42 $ppl_extra || true
    fi
done

# raw logits are only useful while this sweep runs; they are gigabytes
if [ -f "$OUT/logits-baseline.bin" ] && [ "${KV_KEEP_LOGITS:-0}" != 1 ]; then
    rm -f "$OUT/logits-baseline.bin"
    status "removed logits-baseline.bin (set KV_KEEP_LOGITS=1 to keep it)"
fi

status "done in $(( ($(date +%s) - START) / 60 ))m $(free_mem)"
status "results: $OUT"
"$ROOT/kv-bench/report.py" "$OUT" || true
