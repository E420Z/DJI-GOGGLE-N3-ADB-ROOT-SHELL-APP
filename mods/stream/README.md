# mods/stream — PC screen into the goggles

The device half lives in `mods/capture/mod.c` (built as `hook_overlay.so`): it
watches `/data/local/tmp/fb_override` and copies frames from
`/data/local/tmp/fb_shared` into the live display buffer.

This folder adds the other half: `fb_receiver`, a small aarch64 binary that
listens for JPEG frames and publishes them into that shared buffer.

```
PC (PIL ImageGrab -> JPEG)  --TCP 5570-->  fb_receiver
    -> /data/local/tmp/fb_shared (64-byte header, counter at 0, 2 x 8,294,400 B BGRA)
    -> hook_overlay.so inject thread -> display
```

## Frame format

```
[u32le jpeg_len][jpeg bytes]   repeated
```

The receiver scales/letterboxes any size to 1920x1080 and converts RGB -> BGRA.

## Build

```powershell
zig cc -target aarch64-linux-musl -static -O2 `
  -I "C:\N3 goggles\natartos-src\include" `
  -o mods\stream\fb_receiver mods\stream\fb_receiver.c -lm
```

`stb_image.h` (public domain) comes from the natartos include folder and is
compiled in; the resulting binary is ~1.7 MB and fully static.

## Run

The binary must run in the `u:r:su:s0` domain, i.e. over root ADB — the
`dji_services` root shell cannot execute ELF files from `/data` (see
`docs/ADB-ROOT.md`). The file must keep its default `system_data_file` label.

```sh
adb shell 'cd /data/local/tmp && setsid ./fb_receiver >/dev/null 2>&1 &'
```

Stop with `pkill -TERM fb_receiver`: it removes `fb_override`, touches
`fb_stop` so the hook stops injecting, and the live UI repaints.

## Safety

- Writes only `/data/local/tmp/fb_shared`, `fb_override`, `fb_stop`, `fb_receiver.log`.
- Publishes a valid idle frame before setting `fb_override`, so the first frame
  the goggles shows is never uninitialised memory.
- Never touches `/system`, `/vendor`, verity or partitions.
