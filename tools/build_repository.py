#!/usr/bin/env python3
"""拡張機能リポジトリ（index.json）を作る。

    python tools/build_repository.py

1. addons/ の各アドオンを拡張機能パッケージ（zip）にビルドする
2. repository/ に zip を集める
3. `blender --command extension server-generate --repo-dir=repository --html` で
   index.json（Blender が読むリポジトリ一覧）と index.html（人間用の一覧）を作る

Blender の「エクステンションを入手 → リポジトリ → 追加 → リモートリポジトリ」に貼るのは
**repository/index.json の URL**（GitHub のリポジトリ URL ではない）。
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO_DIR = os.path.join(ROOT, "repository")


def find_blender():
    env = os.environ.get("BLENDER_BIN")
    if env and os.path.isfile(env):
        return env
    found = glob.glob("C:/Program Files/Blender Foundation/*/blender.exe")
    if found:
        def key(path):
            raw = re.sub(r"[^0-9.]", "", os.path.basename(os.path.dirname(path)))
            return tuple(int(x) for x in raw.split(".") if x) or (0,)
        return sorted(found, key=key)[-1]
    return shutil.which("blender")


def build_zips(blender, out_dir):
    made = []
    for manifest in sorted(glob.glob(os.path.join(ROOT, "addons", "*", "blender_manifest.toml"))):
        pkg = os.path.dirname(manifest)
        res = subprocess.run([blender, "--command", "extension", "build"],
                             cwd=pkg, capture_output=True, text=True)
        zips = glob.glob(os.path.join(pkg, "*.zip"))
        if res.returncode != 0 or not zips:
            tail = ((res.stdout or "") + (res.stderr or "")).strip().splitlines()[-1:]
            print("[FAIL]", os.path.basename(pkg), tail)
            continue
        for z in zips:
            dest = os.path.join(out_dir, os.path.basename(z))
            shutil.move(z, dest)
            made.append(dest)
            print("[ OK ]", os.path.basename(dest))
    return made


def main():
    ap = argparse.ArgumentParser(prog="build_repository.py")
    ap.add_argument("--no-build", action="store_true",
                    help="zip を作り直さず、repository/ の中身だけで index.json を作る")
    args = ap.parse_args()

    blender = find_blender()
    if not blender:
        print("Blender が見つかりません。環境変数 BLENDER_BIN に blender.exe を設定してください。")
        return 2
    print("Blender:", blender)

    os.makedirs(REPO_DIR, exist_ok=True)
    if not args.no_build:
        for old in glob.glob(os.path.join(REPO_DIR, "*.zip")):
            os.remove(old)
        build_zips(blender, REPO_DIR)

    res = subprocess.run([blender, "--command", "extension", "server-generate",
                          "--repo-dir=%s" % REPO_DIR, "--html"],
                         capture_output=True, text=True)
    blob = ((res.stdout or "") + (res.stderr or "")).strip().splitlines()
    if res.returncode != 0:
        print("[FAIL] server-generate:")
        for line in blob[-4:]:
            print("   ", line)
        return 1

    index = os.path.join(REPO_DIR, "index.json")
    if not os.path.isfile(index):
        print("[FAIL] index.json が生成されなかった")
        return 1
    print("[ OK ] 生成:", index, os.path.getsize(index), "bytes")
    for extra in ("index.html",):
        path = os.path.join(REPO_DIR, extra)
        if os.path.isfile(path):
            print("[ OK ] 生成:", path, os.path.getsize(path), "bytes")
    print("")
    print("Blender に入れる URL はこの index.json（例）:")
    print("  https://unotchi.com/unotchi-blender-addons/repository/index.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
