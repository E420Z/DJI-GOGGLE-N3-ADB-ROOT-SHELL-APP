import os
import subprocess
import sys

INC = r"C:\N3 goggles\natartos-src\include"
SRC = r"C:\N3 goggles\re\n3mods.c"
OUT = r"C:\N3 goggles\ROOT docs\ROOT app\assets\mods\n3mods.so"
cmd = [sys.executable, "-m", "ziglang", "cc",
       "-target", "aarch64-linux-gnu", "-shared", "-fPIC", "-nostdlib",
       "-O2", "-fno-builtin", "-I", INC, "-Wl,-soname,n3mods.so",
       "-o", OUT, SRC]
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout)
print(r.stderr)
print("exit", r.returncode, "size", os.path.getsize(OUT) if os.path.exists(OUT) else 0)
