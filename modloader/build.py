"""Build the flat /vendor mod loader for the N3 app."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
INC = os.path.join(APP, "sdk", "include")
SRC = os.path.join(HERE, "n3mods.c")
OUT = os.path.join(APP, "app", "assets", "mods", "n3mods.so")

cmd = [sys.executable, "-m", "ziglang", "cc",
       "-target", "aarch64-linux-gnu", "-shared", "-fPIC", "-nostdlib",
       "-O2", "-fno-builtin", "-I", INC,
       "-Wl,-soname,n3mods.so", "-o", OUT, SRC]
print("building", OUT)
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout)
print(r.stderr)
print("exit", r.returncode,
      "size", os.path.getsize(OUT) if os.path.exists(OUT) else 0)
