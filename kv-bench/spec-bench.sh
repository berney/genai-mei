#!/bin/sh
#
# Speculative-decoding draft KV-cache sweep for a compose-hosted llama.cpp model.
#
#   ./kv-bench/spec-bench.sh [service]
#
# llama-bench has no speculative-decoding support, so this drives llama-server
# itself: one server per variant (started with `docker compose run` against the
# model's own service definition, so mounts/env/network come from
# docker-compose.yml), a greedy HTTP probe through it, then the container is
# torn down.
#
# Variants (SPEC_VARIANTS): "none" means no speculation at all -- the speed
# baseline. The others imply --spec-type draft-mtp with an MTP head and set
# -ctkd/-ctvd (--cache-type-k-draft / --cache-type-v-draft, env
# LLAMA_ARG_SPEC_DRAFT_CACHE_TYPE_K / _V) to that type. The *target* cache stays
# f16 in every variant; only the draft cache changes.
#
# The binary matters: unsloth's MTP heads (shared or self-contained) omit
# tensors that mainline llama.cpp requires -- output_hc_norm.weight, and for the
# shared heads token_embd/output -- on the expectation that they are borrowed
# from the target at load. The stock image build has no borrow_shared, so it
# fails with "check_tensor_dims: tensor '...' not found" and never starts.
# Point SPEC_SERVER/SPEC_LD at an unsloth build for this model:
#
#   mkdir -p ~/.cache/huggingface/llama-build/b10909-mix
#   curl -L -o /tmp/u.tar.gz https://github.com/unslothai/llama.cpp/releases/download/\
# b10909-mix-bea84f7/app-b10909-mix-bea84f7-linux-x64-rocm-gfx1151.tar.gz
#   tar xzf /tmp/u.tar.gz -C ~/.cache/huggingface/llama-build/b10909-mix
#
# (that directory is inside the mounted HF cache, hence the /huggingface path).
#
# Recorded per variant in results/<stamp>/:
#   spec-<v>.json      tokens/s per prompt + overall, output hash
#   spec-<v>.txt       generated text (diff across variants = token divergence)
#   spec-<v>.metrics   Prometheus scrape: spec/draft counters, KV capacity
#   spec-<v>.log       server stdout/stderr (draft load, KV buffers, spec stats)
#   spec-<v>.create.log  compose/CLI level output
#
# Variables:
#   SPEC_VARIANTS  space separated (default: "none f16 q8_0 q4_0")
#   SPEC_SERVER    llama-server binary *inside the container* (default: llama-server)
#   SPEC_LD        LD_LIBRARY_PATH for SPEC_SERVER's bundled libs (default: unset)
#   SPEC_DRAFT     MTP head path inside the container (default: the shared-Q8_0
#                  head in the model snapshot's MTP/ subdir)
#   SPEC_CTX       --ctx-size (default: 16384)
#   SPEC_NMAX      --spec-draft-n-max (default: 2, unsloth's recommended value)
#   SPEC_TOKENS    generated tokens per request (default: 192)
#   SPEC_PORT      host port the test server is published on (default: 9161)
#   SPEC_STOP      1 (default) stops llama-swap + model + comfyui while running
#   SPEC_LIMIT     probe only the first N prompts, 0 = all (default: 0)
#
set -eu
export PODMAN_COMPOSE_WARNING_LOGS=false

KV_SERVICE="${1:-qwen3.8-Flash-Next-IQ4}"
SPEC_VARIANTS="${SPEC_VARIANTS:-none f16 q8_0 q4_0}"
SPEC_CTX="${SPEC_CTX:-16384}"
SPEC_NMAX="${SPEC_NMAX:-2}"
SPEC_TOKENS="${SPEC_TOKENS:-192}"
SPEC_PORT="${SPEC_PORT:-9161}"
SPEC_STOP="${SPEC_STOP:-1}"
SPEC_LIMIT="${SPEC_LIMIT:-0}"
SPEC_SERVER="${SPEC_SERVER:-llama-server}"
SPEC_LD="${SPEC_LD:-}"

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/kv-bench/results/$(date +%Y%m%d-%H%M%S)"
START=$(date +%s)
mkdir -p "$OUT"

MODEL=$(docker compose run --rm --no-deps -T --entrypoint printenv "$KV_SERVICE" LLAMA_ARG_MODEL 2>/dev/null | tail -1)
[ -n "$MODEL" ] || { echo "could not resolve LLAMA_ARG_MODEL for $KV_SERVICE" >&2; exit 1; }

# The MTP heads live in an MTP/ subdir of the snapshot; sidecar auto-discovery
# does not look there, so the path always has to be explicit.
if [ -z "${SPEC_DRAFT:-}" ]; then
    snap=$(dirname "$(dirname "$MODEL")")
    SPEC_DRAFT="$snap/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf"
fi

. "$ROOT/kv-bench/lib.sh"

status "service: $KV_SERVICE"
status "model:   $MODEL"
status "draft:   $SPEC_DRAFT"
status "server:  $SPEC_SERVER (LD_LIBRARY_PATH=${SPEC_LD:-<image default>})"
status "variants: $SPEC_VARIANTS  n_max=$SPEC_NMAX ctx=$SPEC_CTX tokens=$SPEC_TOKENS port=$SPEC_PORT"

if [ "$SPEC_STOP" = 1 ]; then
    svc_stop
fi
status "memory: $(free_mem)"

wait_health() {
    # 93 GB of weights plus the draft head: allow a slow load. Returns 2 when
    # the container died, so a load failure is reported in seconds, not 8 minutes.
    i=0
    while [ "$i" -le 240 ]; do
        curl -sf "http://127.0.0.1:${SPEC_PORT}/health" >/dev/null 2>&1 && return 0
        [ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" = false ] && return 2
        i=$((i + 1))
        sleep 2
    done
    return 1
}

# launch_server <name> <server args...>
# No --rm: a container that dies during load is the only copy of the error.
# ${SPEC_LD:+...} relies on the library path containing no spaces.
launch_server() {
    name=$1
    shift
    docker compose run -d --no-deps --name "$name" \
        -p "127.0.0.1:${SPEC_PORT}:8080" \
        -e HSA_ENABLE_SDMA=0 \
        ${SPEC_LD:+-e LD_LIBRARY_PATH=$SPEC_LD} \
        --entrypoint "$SPEC_SERVER" "$KV_SERVICE" "$@"
}

for v in $SPEC_VARIANTS; do
    cname="kv-spec-$v"
    set -- -m "$MODEL" -ngl 999 -fa on --ctx-size "$SPEC_CTX" --parallel 1 \
        --no-warmup --metrics --temp 0 --presence-penalty 0 --repeat-penalty 1.0 \
        --host 0.0.0.0 --port 8080
    if [ "$v" != none ]; then
        set -- "$@" -md "$SPEC_DRAFT" --spec-type draft-mtp --spec-draft-n-max "$SPEC_NMAX" \
            -ctkd "$v" -ctvd "$v"
    fi

    status "== server $v ($(( $(date +%s) - START ))s elapsed)"
    # shellcheck disable=SC2086
    if ! launch_server "$cname" "$@" >>"$OUT/spec-$v.create.log" 2>&1; then
        status "FAIL server $v (compose run failed) -- see spec-$v.create.log"
        continue
    fi

    rc=0
    wait_health || rc=$?
    if [ "$rc" != 0 ]; then
        if [ "$rc" = 2 ]; then
            status "FAIL server $v (llama-server exited during load)"
        else
            status "FAIL server $v (no /health in 480s)"
        fi
        docker logs "$cname" >"$OUT/spec-$v.log" 2>&1 || true
        tail -12 "$OUT/spec-$v.log" | tee -a "$OUT/STATUS" || true
        docker rm -f "$cname" >>"$OUT/spec-$v.create.log" 2>&1 || true
        continue
    fi
    status "   healthy after $((i * 2))s"

    if "$ROOT/kv-bench/spec-probe.py" --url "http://127.0.0.1:${SPEC_PORT}" \
        --label "$v" --tokens "$SPEC_TOKENS" --limit "$SPEC_LIMIT" \
        --out "$OUT/spec-$v" >>"$OUT/spec-$v.log" 2>&1; then
        status "ok   probe $v  $(free_mem)"
        # acceptance stats: these counters move only if speculation actually ran
        grep -iE "spec|draft" "$OUT/spec-$v.metrics" 2>/dev/null | grep -v '^#' \
            | tee -a "$OUT/STATUS" || status "   (no spec/draft counters in /metrics)"
    else
        status "FAIL probe $v -- see spec-$v.log"
    fi

    docker logs "$cname" >>"$OUT/spec-$v.log" 2>&1 || true
    docker rm -f "$cname" >>"$OUT/spec-$v.create.log" 2>&1 || true
    sleep 3
done

status "done in $(( ($(date +%s) - START) / 60 ))m $(free_mem)"
status "results: $OUT"
"$ROOT/kv-bench/report.py" "$OUT" || true
