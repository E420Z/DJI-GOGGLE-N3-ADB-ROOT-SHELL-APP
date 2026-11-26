#!/system/bin/sh
# s2cap.sh - receive-only Sparrow2 (S2) video capture helper.
#
# Part of N3 ROOT. Installed to /data/local/tmp/s2cap.sh by the "S2 capture"
# mod. Everything here is read-only with respect to the device: it reads the
# vendor USB video endpoints through the shipped decoder and writes only under
# /data/local/tmp/s2cap. No /system, no verity, no partition, no RF transmit.
#
# Usage:
#   s2cap.sh probe
#   s2cap.sh list
#   s2cap.sh start <main|secondary|none> <seconds>      # dump encoded stream
#   s2cap.sh record <seconds>                           # omx_recordtest route
#   s2cap.sh stop
#   s2cap.sh status
#
# "start main" tries -p 0 (main 1920x1080). Some builds reject -p; use "none"
# to omit it, or let the app retry automatically.

OUT=/data/local/tmp/s2cap
BIN=/system/bin/test_wl_vdec
[ -x "$BIN" ] || BIN=/data/local/tmp/test_wl_vdec
PIDF=$OUT/pid

log() { echo "$*"; }

probe() {
  log "== decoder =="
  ls -l /system/bin/test_wl_vdec /data/local/tmp/test_wl_vdec 2>&1
  log "== option letters found in the binary =="
  [ -f "$BIN" ] && grep -a -o -- '-[A-Za-z][ ,]' "$BIN" 2>/dev/null | tr -d ' ,' | sort -u | tr '\n' ' '
  log ""
  log "== record tools =="
  ls -l /system/bin/omx_recordtest /system/bin/record_test_script.sh \
        /data/local/tmp/omx_recordtest 2>&1
  log "== usb ids (looking for 2ca3:1020) =="
  for d in /sys/bus/usb/devices/*; do
    [ -r "$d/idVendor" ] || continue
    v=$(cat "$d/idVendor" 2>/dev/null)
    p=$(cat "$d/idProduct" 2>/dev/null)
    [ "$v" = "2ca3" ] && log "  $d  $v:$p"
  done
  log "== wlm config =="
  for f in /vendor/etc/wlm_cfg.json /etc/wlm_cfg.json \
           /data/vendor/wlm/wlm_cfg.json /vendor/wlm_cfg.json; do
    if [ -f "$f" ]; then
      log "  found $f"
      grep -a -o 'test\.liveview[^,}]*' "$f" 2>/dev/null | head -5
    fi
  done
  log "== blackbox recordings =="
  ls -l /blackbox/record 2>&1 | head -10
  log "== existing capture dir =="
  ls -l "$OUT" 2>&1 | head -10
}

list() {
  ls -l "$OUT" 2>&1
}

stop() {
  if [ -f "$PIDF" ]; then
    kill "$(cat "$PIDF")" 2>/dev/null
    sleep 1
    kill -9 "$(cat "$PIDF")" 2>/dev/null
    rm -f "$PIDF"
    log "stopped test_wl_vdec"
  else
    # no pidfile: only touch our own decoder, never anything else
    for p in $(pidof test_wl_vdec 2>/dev/null); do
      kill "$p" 2>/dev/null
      log "killed stray test_wl_vdec pid $p"
    done
  fi
}

start() {
  mode=${1:-main}
  secs=${2:-8}
  case "$mode" in
    main)      IFACE=main; NAME=s2_main; W=1920; H=1080; P=0 ;;
    secondary) IFACE=secondary; NAME=s2_sec; W=640; H=360; P=1 ;;
    none)      IFACE=none; NAME=s2_auto; W=1920; H=1080; P="" ;;
    *) log "unknown mode: $mode (use main|secondary|none)"; exit 2 ;;
  esac
  [ -x "$BIN" ] || { log "missing decoder: $BIN"; exit 3; }

  mkdir -p "$OUT" || { log "cannot create $OUT"; exit 4; }
  stop >/dev/null 2>&1
  rm -f "$OUT"/s2_* "$OUT"/run.log 2>/dev/null

  log "capture: iface=$IFACE ${W}x${H} ${secs}s -> $OUT"
  cd "$OUT" || exit 4

  if [ -n "$P" ]; then
    "$BIN" -t usb_vdec -p "$P" -F 1 -w "$W" -h "$H" -C yuv420 -d -e "$OUT" -b "$NAME" \
      > run.log 2>&1 &
  else
    "$BIN" -t usb_vdec -F 1 -w "$W" -h "$H" -C yuv420 -d -e "$OUT" -b "$NAME" \
      > run.log 2>&1 &
  fi
  echo $! > "$PIDF"
  sleep "$secs"
  stop >/dev/null 2>&1

  log "== run.log =="
  tail -20 run.log 2>/dev/null
  log "== files =="
  ls -l "$OUT" 2>&1
}

status() {
  if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
    log "running pid $(cat "$PIDF")"
  else
    log "idle"
  fi
  ls -l "$OUT" 2>&1 | head -10
}

case "$1" in
  probe)  probe ;;
  list)   list ;;
  start)  shift; start "$@" ;;
  record) log "record route is not enabled in this build"; exit 5 ;;
  stop)   stop ;;
  status) status ;;
  *)      sed -n '2,20p' "$0" ;;
esac
