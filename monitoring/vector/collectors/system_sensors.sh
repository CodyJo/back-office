#!/bin/bash
# Collects CPU temperature, frequency, page faults, OOM kills, swap I/O
# from /sys/ and /proc/. These are NOT available from Vector's host_metrics.
# Outputs JSON array. Exits 0 with zero-values on failure.
set -euo pipefail

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
METRICS="["
FIRST=true
HOST_SYS="${HOST_SYS:-/host/sys}"
HOST_PROC="${HOST_PROC:-/host/proc}"

if [ ! -d "$HOST_SYS" ] && [ -d /sys ]; then
    HOST_SYS="/sys"
fi

if [ ! -d "$HOST_PROC" ] && [ -d /proc ]; then
    HOST_PROC="/proc"
fi

add_metric() {
    local source="$1" metric="$2" labels="$3" value="$4"
    if [ "$FIRST" = true ]; then FIRST=false; else METRICS+=","; fi
    METRICS+="$(printf '\n  {"time":"%s","source":"%s","metric":"%s","labels":%s,"value":%s}' \
        "$NOW" "$source" "$metric" "$labels" "$value")"
}

# ── CPU Temperature (k10temp) ────────────────────────────────
# Find the k10temp hwmon directory
HWMON_DIR=""
for d in "$HOST_SYS"/class/hwmon/hwmon*/; do
    if [ -f "${d}name" ] && [ "$(cat "${d}name" 2>/dev/null)" = "k10temp" ]; then
        HWMON_DIR="$d"
        break
    fi
done

if [ -n "$HWMON_DIR" ]; then
    # Tctl (overall die temp) is usually temp1
    for temp_file in "${HWMON_DIR}"temp*_input; do
        [ -f "$temp_file" ] || continue
        label_file="${temp_file%_input}_label"
        label="unknown"
        [ -f "$label_file" ] && label=$(cat "$label_file" 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr ' ' '_')
        raw=$(cat "$temp_file" 2>/dev/null || echo 0)
        # /sys reports millidegrees
        temp_c=$(echo "scale=1; $raw / 1000" | bc 2>/dev/null || echo 0)
        add_metric "sensors" "cpu_temp_celsius" "{\"sensor\":\"k10temp\",\"label\":\"$label\"}" "$temp_c"
    done
fi

# ── CPU Frequency ────────────────────────────────────────────
core=0
for freq_file in "$HOST_SYS"/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq; do
    [ -f "$freq_file" ] || continue
    raw=$(cat "$freq_file" 2>/dev/null || echo 0)
    # /sys reports kHz
    freq_mhz=$(echo "scale=0; $raw / 1000" | bc 2>/dev/null || echo 0)
    add_metric "sensors" "cpu_freq_mhz" "{\"core\":\"$core\"}" "$freq_mhz"
    core=$((core + 1))
done

# ── /proc/vmstat counters ────────────────────────────────────
VMSTAT="$HOST_PROC/vmstat"
if [ -f "$VMSTAT" ]; then
    pgmajfault=$(grep -w pgmajfault "$VMSTAT" 2>/dev/null | awk '{print $2}' || echo 0)
    oom_kill=$(grep -w oom_kill "$VMSTAT" 2>/dev/null | awk '{print $2}' || echo 0)
    pswpin=$(grep -w pswpin "$VMSTAT" 2>/dev/null | awk '{print $2}' || echo 0)
    pswpout=$(grep -w pswpout "$VMSTAT" 2>/dev/null | awk '{print $2}' || echo 0)

    add_metric "sensors" "memory_page_faults_major" "{}" "$pgmajfault"
    add_metric "sensors" "oom_kills_total" "{}" "$oom_kill"
    add_metric "sensors" "swap_io_in_pages" "{}" "$pswpin"
    add_metric "sensors" "swap_io_out_pages" "{}" "$pswpout"
fi

METRICS+="\n]"
echo -e "$METRICS"
