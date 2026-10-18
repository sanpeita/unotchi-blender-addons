#!/usr/bin/env python3
"""addons/ 配下の全アドオンを拡張機能パッケージ（zip）にビルドする。

    python tools/build_all.py            # releases/ に zip を作る
    python tools/build_all.py --dry-run

Blender 4.2 以降が必要（拡張機能の build コマンドを使う）。
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def find_blender():
    env = os.environ.get("BLENDER_BIN")
    if env and os.path.isfile(env):
        return env
    found = glob.glob("C:/Program Files/Blender Foundation/*/blender.exe")
    if found:
        def key(p):
            raw = re.sub(r"[^0-9.]", "", os.path.basename(os.path.dirname(p)))
            return tuple(int(x) for x in raw.split(".") if x) or (0,)
        return sorted(found, key=key)[-1]
    return shutil.which("blender")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    blender = find_blender()
    if not blender:
        print("Blender が見つかりません。BLENDER_BIN を設定してください。")
        return 2
    print("Blender:", blender)

    out_dir = os.path.join(ROOT, "releases")
    os.makedirs(out_dir, exist_ok=True)
    ok = True
    for manifest in sorted(glob.glob(os.path.join(ROOT, "addons", "*", "blender_manifest.toml"))):
        pkg = os.path.dirname(manifest)
        name = os.path.basename(pkg)
        if args.dry_run:
            print("[dry-run]", name)
            continue
        res = subprocess.run([blender, "--command", "extension", "build"],
                             cwd=pkg, capture_output=True, text=True)
        zips = glob.glob(os.path.join(pkg, "*.zip"))
        if res.returncode != 0 or not zips:
            print("[FAIL]", name, (res.stdout or res.stderr or "").strip().splitlines()[-1:])
            ok = False
            continue
        for z in zips:
            shutil.move(z, os.path.join(out_dir, os.path.basename(z)))
            print("[ OK ]", os.path.basename(z))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
