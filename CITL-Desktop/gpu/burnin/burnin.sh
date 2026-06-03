#!/usr/bin/env bash
set -euo pipefail
LOGDIR=/var/log/flexcoach-gpu; mkdir -p "$LOGDIR"
TS=$(date +%Y%m%d-%H%M%S); LOG="$LOGDIR/gpu-burn_$TS.log"

echo "== FLEX GPU Burn-in $(date) ==" | tee -a "$LOG"
nvidia-smi -L | tee -a "$LOG"
nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,power.draw --format=csv | tee -a "$LOG"

# Prefer Docker; fallback to native
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  git clone https://github.com/wilicc/gpu-burn /tmp/gpu-burn && cd /tmp/gpu-burn
  docker build -t gpu_burn . >>"$LOG" 2>&1
  ( docker run --rm --gpus all gpu_burn ./gpu_burn -m 90% 1800 ) 2>&1 | tee -a "$LOG"
else
  git clone https://github.com/wilicc/gpu-burn /tmp/gpu-burn && cd /tmp/gpu-burn
  make COMPUTE=75 >>"$LOG" 2>&1
  ( ./gpu_burn -m 90% 1800 ) 2>&1 | tee -a "$LOG"
fi

echo "== Post-run telemetry ==" | tee -a "$LOG"
nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,power.draw --format=csv | tee -a "$LOG"
echo "Logs: $LOG"
