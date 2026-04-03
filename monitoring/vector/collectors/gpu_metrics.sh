#!/bin/bash
# Collects NVIDIA GPU metrics via nvidia-smi.
# Outputs JSON array of metric objects for Vector exec source.
# Exits 0 with zero-values if nvidia-smi is unavailable.
set -euo pipefail

NVIDIA_SMI="${NVIDIA_SMI:-nvidia-smi}"
GPU_LABEL="rtx3080"

if ! command -v "$NVIDIA_SMI" &>/dev/null; then
    echo '[]'
    exit 0
fi

RAW=$("$NVIDIA_SMI" --query-gpu=\
temperature.gpu,\
utilization.gpu,\
memory.used,\
memory.total,\
memory.free,\
power.draw,\
power.limit,\
clocks.current.graphics,\
clocks.max.graphics,\
fan.speed,\
clocks_throttle_reasons.gpu_idle,\
clocks_throttle_reasons.hw_thermal_slowdown,\
clocks_throttle_reasons.sw_thermal_slowdown,\
clocks_throttle_reasons.sw_power_cap,\
pcie.link.gen.current,\
pcie.link.width.current \
--format=csv,noheader,nounits 2>/dev/null) || { echo '[]'; exit 0; }

IFS=', ' read -r \
    temp util mem_used mem_total mem_free \
    power power_limit clock_cur clock_max fan \
    thr_idle thr_hw_thermal thr_sw_thermal thr_sw_power \
    pcie_gen pcie_width <<< "$RAW"

# Convert MiB to bytes
mem_used_b=$(( ${mem_used:-0} * 1048576 ))
mem_total_b=$(( ${mem_total:-0} * 1048576 ))
mem_free_b=$(( ${mem_free:-0} * 1048576 ))

# Map "Active"/"Not Active" to 1/0 for throttle reasons
thr_val() {
    case "${1,,}" in
        active|1) echo 1 ;;
        *) echo 0 ;;
    esac
}

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

cat << ENDJSON
[
  {"time":"$NOW","source":"gpu","metric":"gpu_temp_celsius","labels":{"gpu":"$GPU_LABEL"},"value":${temp:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_utilization_percent","labels":{"gpu":"$GPU_LABEL"},"value":${util:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_memory_used_bytes","labels":{"gpu":"$GPU_LABEL"},"value":$mem_used_b},
  {"time":"$NOW","source":"gpu","metric":"gpu_memory_total_bytes","labels":{"gpu":"$GPU_LABEL"},"value":$mem_total_b},
  {"time":"$NOW","source":"gpu","metric":"gpu_memory_free_bytes","labels":{"gpu":"$GPU_LABEL"},"value":$mem_free_b},
  {"time":"$NOW","source":"gpu","metric":"gpu_power_watts","labels":{"gpu":"$GPU_LABEL"},"value":${power:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_power_limit_watts","labels":{"gpu":"$GPU_LABEL"},"value":${power_limit:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_clock_current_mhz","labels":{"gpu":"$GPU_LABEL"},"value":${clock_cur:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_clock_max_mhz","labels":{"gpu":"$GPU_LABEL"},"value":${clock_max:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_fan_percent","labels":{"gpu":"$GPU_LABEL"},"value":${fan:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_throttle_idle","labels":{"gpu":"$GPU_LABEL"},"value":$(thr_val "$thr_idle")},
  {"time":"$NOW","source":"gpu","metric":"gpu_throttle_hw_thermal","labels":{"gpu":"$GPU_LABEL"},"value":$(thr_val "$thr_hw_thermal")},
  {"time":"$NOW","source":"gpu","metric":"gpu_throttle_sw_thermal","labels":{"gpu":"$GPU_LABEL"},"value":$(thr_val "$thr_sw_thermal")},
  {"time":"$NOW","source":"gpu","metric":"gpu_throttle_sw_power_cap","labels":{"gpu":"$GPU_LABEL"},"value":$(thr_val "$thr_sw_power")},
  {"time":"$NOW","source":"gpu","metric":"gpu_pcie_link_gen","labels":{"gpu":"$GPU_LABEL"},"value":${pcie_gen:-0}},
  {"time":"$NOW","source":"gpu","metric":"gpu_pcie_link_width","labels":{"gpu":"$GPU_LABEL"},"value":${pcie_width:-0}}
]
ENDJSON
