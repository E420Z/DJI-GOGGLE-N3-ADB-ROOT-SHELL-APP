"""Build the stock-menu row injector."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(HERE))
INC = os.path.join(APP, "sdk", "include")
OUT = os.path.join(APP, "app", "plugins", "menuinject", "files",
                   "n3menuinject.so")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
cmd = [sys.executable, "-m", "ziglang", "cc",
       "-target", "aarch64-linux-gnu", "-shared", "-fPIC", "-nostdlib",
       "-O2", "-fno-builtin", "-I", INC, "-I", HERE,
       "-Wl,-soname,n3menuinject.so", "-o", OUT,
       os.path.join(HERE, "mod.c")]
print("building", OUT)
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout)
print(r.stderr)
print("exit", r.returncode,
      "size", os.path.getsize(OUT) if os.path.exists(OUT) else 0)
