#!/system/bin/sh
# /data/dji/boot.sh - N3 boot persistence via the stock sys_perf log service.
# Runs as root in u:r:dji_services:s0.  No /system, /vendor or sepolicy writes.
# Gate: /data/dji/enabled.  Remove that file (or use the app) to stay stock.

LOG=/data/dji/boot.log
ENABLED=/data/dji/enabled
FAIL=/data/dji/boot_fail_count
BOOTID_FILE=/data/dji/last_boot_id
APPS=/data/dji/apps
UI=/vendor/dji_glasses_patched
LIB=/vendor/libew_gls.so
BG_HOOK=/vendor/n3bg.so
BG1=/vendor/background.jpg
BG2=/vendor/background_idle.jpg
MOD_LOADER=/vendor/n3mods.so
MOD_LIST=/data/local/tmp/n3mods.list

PATH=/system/bin:/system/xbin:/vendor/bin:$PATH
export PATH

mkdir -p /data/dji "$APPS" 2>/dev/null

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

is_patched() { ps -A 2>/dev/null | grep -q 'dji_glasses_pat'; }
is_stock()   { ps -A 2>/dev/null | grep -q ' dji_glasses$'; }

kill_ui() {
    setprop ctl.stop dji_glasses 2>/dev/null
    sleep 1
    for p in $(ps -A 2>/dev/null | grep dji_glasses | tr -s ' ' | cut -d' ' -f2); do
        kill -9 "$p" 2>/dev/null
    done
    sleep 1
}

start_patched() {
    pre=""
    [ -f "$MOD_LOADER" ] && [ -f "$MOD_LIST" ] && pre="$MOD_LOADER"
    if [ -f "$BG_HOOK" ] && [ -f "$BG1" ] && [ -f "$BG2" ]; then
        if [ -n "$pre" ]; then pre="$pre:$BG_HOOK"; else pre="$BG_HOOK"; fi
    fi
    if [ -n "$pre" ]; then
        env LD_LIBRARY_PATH=/vendor LD_PRELOAD="$pre" \
            setsid "$UI" -g -f >>"$LOG" 2>&1 </dev/null &
    else
        env LD_LIBRARY_PATH=/vendor \
            setsid "$UI" -g -f >>"$LOG" 2>&1 </dev/null &
    fi
}

start_stock() {
    setprop ctl.start dji_glasses 2>/dev/null
}

rearm() {
    for d in 0 1 2 3; do
        mkdir -p "/blackbox/system/sys_perf/$d" 2>/dev/null
        i=1
        while [ "$i" -le 4 ]; do
            touch "/blackbox/system/sys_perf/$d/ktop.log.999990${i};x=\${PATH:0:1};sh \${x}data\${x}dji\${x}boot.sh" 2>/dev/null
            i=$((i + 1))
        done
    done
}

start_apps() {
    for s in "$APPS"/*.sh; do
        [ -f "$s" ] || continue
        b=${s%.sh}
        [ -f "$b.on" ] || continue
        log "app: $s"
        sh "$s" >>"$LOG" 2>&1 &
    done
    for a in /vendor/n3app_*; do
        [ -x "$a" ] || continue
        b=$(basename "$a")
        [ -f "$APPS/$b.on" ] || continue
        log "vendor app: $a"
        "$a" >>"$LOG" 2>&1 &
    done
}

log "=== boot.sh start (uptime $(cut -d. -f1 /proc/uptime 2>/dev/null)s) ==="

if [ ! -f "$ENABLED" ]; then
    log "disabled (no $ENABLED); stock stays"
    rearm
    log "=== boot.sh end (disabled) ==="
    exit 0
fi

bid=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
last=$(cat "$BOOTID_FILE" 2>/dev/null)
if [ -n "$bid" ] && [ "$bid" = "$last" ]; then
    log "already handled boot $bid; rearm only"
    rearm
    log "=== boot.sh end (already ran) ==="
    exit 0
fi
[ -n "$bid" ] && echo "$bid" > "$BOOTID_FILE"

if [ -f "$UI" ] && [ -f "$LIB" ]; then
    log "starting patched UI"
    kill_ui
    start_patched
    sleep 5
    if is_patched; then
        log "patched UI healthy"
        echo 0 > "$FAIL" 2>/dev/null
        start_apps
    else
        log "patched UI not running -> stock fallback"
        start_stock
        f=$(cat "$FAIL" 2>/dev/null || echo 0)
        f=$((f + 1))
        echo "$f" > "$FAIL" 2>/dev/null
        if [ "$f" -ge 3 ]; then
            log "3 failed boots -> removing $ENABLED"
            rm -f "$ENABLED"
        fi
    fi
else
    log "no $UI/$LIB; stock stays"
    start_stock
fi

rearm
log "=== boot.sh end ==="
