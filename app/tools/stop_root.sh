#!/system/bin/sh
# kill the temporary root-shell listener on 4444 and its wrapper subshell
for i in 1 2 3 4 5; do
    p=$(netstat -tlnp 2>/dev/null | grep ':4444 ' | head -1 | sed 's/.* \([0-9][0-9]*\)\/.*/\1/')
    [ -z "$p" ] && break
    pp=$(cut -d' ' -f4 /proc/$p/stat 2>/dev/null)
    kill -9 "$p" "$pp" 2>/dev/null
    sleep 1
done
rm -f /data/local/tmp/stop_root.sh
