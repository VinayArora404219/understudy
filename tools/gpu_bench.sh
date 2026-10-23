#!/usr/bin/env bash
# Run a command while sampling the GPU host's VRAM; append a summary to bench/log.tsv.
#   tools/gpu_bench.sh <label> <command...>
# GPU_HOST (ssh target) and COMFY_DIRECT come from the environment or the repo's .env
# (see .env.example). Waits for ComfyUI's queue to be empty first, so a bench run never
# queues behind someone else's job.
set -u
label=$1; shift
here=$(cd "$(dirname "$0")/.." && pwd)
[ -f "$here/.env" ] && set -a && . "$here/.env" && set +a
host=${GPU_HOST:?set GPU_HOST (see .env.example)}
comfy=${COMFY_DIRECT:?set COMFY_DIRECT (see .env.example)}
mkdir -p "$here/bench"

until curl -s --max-time 10 "$comfy/queue" | python3 -c \
  'import json,sys; q=json.load(sys.stdin); sys.exit(0 if not q["queue_running"] and not q["queue_pending"] else 1)'; do
  sleep 30
done

vram=$(mktemp)
ssh "$host" 'nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -l 5' > "$vram" 2>/dev/null &
sampler=$!
t0=$(date +%s)
"$@"
rc=$?
t1=$(date +%s)
kill $sampler 2>/dev/null
peak=$(sort -n "$vram" | tail -1)
rm -f "$vram"
printf '%s\t%s\t%s\t%ss\tpeak_vram_mb=%s\n' "$(date -Iseconds)" "$label" "rc=$rc" "$((t1 - t0))" "${peak:-?}" \
  | tee -a "$here/bench/log.tsv"
exit $rc
