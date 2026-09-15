# Shared helpers for the kv-bench scripts (sourced, not executed).
#
# The caller must set, before sourcing:
#   OUT         results directory (STATUS / stop.log / restore.log land here)
#   KV_SERVICE  compose service hosting the model
#
# Provides status/free_mem, stops llama-swap + the model service + comfyui with
# svc_stop, and guarantees they come back up: lib.sh installs a restore trap,
# which health-checks the model service before the script exits -- including on
# failure or Ctrl-C. Nothing that loads this model can coexist with the running
# service (only ~5 GiB is left once the weights are resident), which is why the
# stop is mandatory for measurement and must never be skippable-by-accident.

status() { echo "$*" | tee -a "$OUT/STATUS"; echo; }

free_mem() { free -h | awk '/^Mem:/ {print $3 " used, " $4 " free (avail " $7 ")"}'; }
[ -n "${OUT:-}" ]       || { echo "kv-bench/lib.sh: set OUT (results dir) before sourcing" >&2; exit 1; }
[ -n "${KV_SERVICE:-}" ] || { echo "kv-bench/lib.sh: set KV_SERVICE before sourcing" >&2; exit 1; }

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

# Stop whatever is running that would contend for memory. Sets STOPPED to what
# actually went down, so restore only starts what it stopped.
svc_stop() {
    STOPPED=$(docker compose ps --services 2>/dev/null \
        | grep -E "^(llama-swap|${KV_SERVICE}|comfyui)$" | tr '\n' ' ')
    [ -n "$STOPPED" ] || { STOPPED=""; return 0; }
    # llama-swap first: while it runs it will respawn the model on request
    status "stopping: $STOPPED"
    docker compose stop llama-swap "$KV_SERVICE" comfyui >>"$OUT/stop.log" 2>&1 || true
    sleep 5
}

# vim: ts=4 sw=4 et
