"""The start screen's update: the latest published release on GitHub, its package for this system downloaded and
checked, and the files the update left behind removed. Run with the package's Python by
runtime/ui/launcher/launcher_update.cpp; the launcher swaps the files itself once this has exited, then runs prepare.py
again without --source (only the steps whose key changed).

Why: players kept reporting from old versions (#28 from 0.1.2-12) and an update by hand means unpacking and preparing
again. The offer at start follows hookshot's host/hos_update.c (GPL-3.0, idea only): a few seconds at most, nothing
offline. Only published releases count. Custom builds also accept published custom prereleases from this fork;
Actions artifacts and drafts are never offered.

Output: one event per line on stdout, as prepare.py's:
  check  "update <tag> <bytes>" when the latest release is newer than --version, "latest" when not
  fetch  "progress <done> <total>", then "ready <path>": the AppImage (Linux) or the package's top folder (Windows)
  clean  "cleaned <n>"
  any    "error <command> <message>"
Exit codes: 0 done, 1 failed.

Usage: python -I update.py check --version VER [--os linux|windows]
       python -I update.py fetch --tag TAG --dest DIR [--os linux|windows]
       python -I update.py clean --game DIR
MKW_UPDATE_REPO=owner/name (default ezfn1804-cell/mkw-recomp) and MKW_UPDATE_AS=<version> (compare as that version: a
test) change what is asked.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import ssl
import stat
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import quote

REPO = os.environ.get("MKW_UPDATE_REPO") or "ezfn1804-cell/mkw-recomp"
CHECK_TIMEOUT = 5  # s: the start screen waits for nothing, but a hung request should not linger
FETCH_TIMEOUT = 30
ASSET_SUFFIX = {"linux": "-x86_64.AppImage", "windows": "-windows-x64.zip"}  # tools/build/release.py's names
CLEAN_WAIT = 20  # s
OLD_SUFFIX = ".old"  # what the launcher renames the replaced files to (Windows: a running exe cannot be removed)
VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:-custom\.([1-9]\d*))?(?:-\d+-g[0-9a-f]+)?(?:-dirty)?")
# These are the distributed files, not the player's data. launcher_update.cpp swaps only the extracted entries.
PACKAGE_FILES = {"mkw.exe", "sdl3.dll", "libopus-0.dll", "diagnose.py", "collect-diagnostic.cmd", "test-windows.md"}
PACKAGE_DIRS = {"setup", "licenses"}


def emit(*words: object) -> None:
    print(*words, flush=True)


def ssl_context() -> ssl.SSLContext:
    """The system's CA store; else pip's bundled one (python-build-standalone ships no certifi, and a minimal Linux
    running the AppImage may have no /etc/ssl)."""
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca"):
        return ctx
    for pem in Path(sys.prefix).glob("lib*/python3*/site-packages/pip/_vendor/certifi/cacert.pem"):
        return ssl.create_default_context(cafile=str(pem))
    for pem in Path(sys.prefix).glob("Lib/site-packages/pip/_vendor/certifi/cacert.pem"):
        return ssl.create_default_context(cafile=str(pem))
    return ctx


def get(url: str, timeout: int) -> urllib.request.addinfourl:
    req = urllib.request.Request(
        url, headers={"User-Agent": "mkw-recomp-launcher", "Accept": "application/vnd.github+json"}
    )
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())


def version_key(v: str) -> tuple[int, int, int, int, int] | None:
    """Order custom.N numerically, then the stable version; accept git-describe suffixes without downgrading them."""
    m = VERSION.fullmatch(v)
    if not m:
        return None
    core = (int(m[1]), int(m[2]), int(m[3]))
    return (*core, 0, int(m[4])) if m[4] else (*core, 1, 0)


def release_asset(rel: dict, os_name: str, allow_custom: bool) -> tuple[str, dict] | None:
    tag = rel.get("tag_name", "")
    key = version_key(tag)
    if rel.get("draft") or key is None:
        return None
    if key[3] == 0 and not allow_custom:
        return None
    if rel.get("prerelease") and not (allow_custom and key[3] == 0):
        return None
    for a in rel.get("assets", []):
        if a["name"].endswith(ASSET_SUFFIX[os_name]):
            return tag, a
    return None


def latest_asset(os_name: str, allow_custom: bool = False) -> tuple[str, dict] | None:
    # Unlike releases/latest, this includes custom.N prereleases deliberately published by the maintainer.
    with get(f"https://api.github.com/repos/{REPO}/releases?per_page=100", CHECK_TIMEOUT) as r:
        releases = json.load(r)
    choices = [a for rel in releases if (a := release_asset(rel, os_name, allow_custom))]
    return max(choices, key=lambda a: version_key(a[0])) if choices else None


def check(args: argparse.Namespace) -> None:
    current = version_key(os.environ.get("MKW_UPDATE_AS") or args.version)
    found = latest_asset(args.os, allow_custom=current is not None and current[3] == 0) if current else None
    if found is None or version_key(found[0]) <= current:
        emit("latest")
        return
    tag, asset = found
    emit("update", tag, asset["size"])


def fetch(args: argparse.Namespace) -> None:
    if version_key(args.tag) is None:
        raise ValueError("invalid release tag")
    # Fetch the offered release, even if another one was published while the player read the offer.
    with get(f"https://api.github.com/repos/{REPO}/releases/tags/{quote(args.tag, safe='')}", CHECK_TIMEOUT) as r:
        rel = json.load(r)
    found = release_asset(rel, args.os, allow_custom=True)
    if found is None or found[0] != args.tag:
        raise ValueError("this release is not published or has no compatible package")
    tag, asset = found
    digest = asset.get("digest") or ""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(f"{asset['name']} has no sha256 on GitHub: not installed")
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", asset["name"]):
        raise ValueError("invalid package filename")
    dest = args.dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    part = dest / (asset["name"] + ".part")
    h, done, total, step = hashlib.sha256(), 0, int(asset["size"]), max(1, int(asset["size"]) // 200)
    with get(asset["browser_download_url"], FETCH_TIMEOUT) as r, part.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            if done // step != (done + len(chunk)) // step:
                emit("progress", done + len(chunk), total)
            done += len(chunk)
    if done != total or "sha256:" + h.hexdigest() != digest:
        part.unlink()
        raise ValueError(f"{asset['name']} came damaged ({done} of {total} bytes or another sha256): try again")
    if args.os == "linux":
        out = dest / asset["name"]
        part.replace(out)
        out.chmod(0o755)
        emit("ready", out)
        return
    new = dest / "new"
    shutil.rmtree(new, ignore_errors=True)
    with zipfile.ZipFile(part) as z:
        validate_windows_package(z)
        z.extractall(new)
    part.unlink()
    tops = [p for p in new.iterdir() if p.is_dir()]
    if len(tops) != 1 or not (tops[0] / "mkw.exe").is_file():
        raise ValueError(f"{asset['name']} is not a package of the port (no mkw-recomp/mkw.exe)")
    emit("ready", tops[0])


def validate_windows_package(z: zipfile.ZipFile) -> None:
    """Keep the launcher's swap away from game data, saves, settings, generated files and caches."""
    names = set()
    for info in z.infolist():
        name = info.filename
        p, win = PurePosixPath(name), PureWindowsPath(name)
        if p.is_absolute() or win.drive or "\\" in name or ".." in p.parts or any(":" in part for part in p.parts):
            raise ValueError("the package holds a path outside its folder")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError("the package holds a symbolic link")
        if not p.parts or p.parts[0] != "mkw-recomp":
            raise ValueError("the package must have a single mkw-recomp folder")
        if len(p.parts) == 1 and info.is_dir():
            continue
        if len(p.parts) < 2:
            raise ValueError("invalid package layout")
        top = p.parts[1].casefold()
        if top not in PACKAGE_DIRS and not (top in PACKAGE_FILES and len(p.parts) == 2 and not info.is_dir()):
            raise ValueError("the package contains files outside the runtime and setup tools")
        normalized = name.casefold()
        if normalized in names:
            raise ValueError("the package contains duplicate paths")
        names.add(normalized)
    if "mkw-recomp/mkw.exe" not in names:
        raise ValueError("the package has no mkw.exe")


def clean(args: argparse.Namespace) -> None:
    """The old program may still be closing when the new one starts this (Windows refuses to remove a running exe):
    each entry is tried again for CLEAN_WAIT seconds."""
    game, n = args.game.resolve(), 0
    for p in game.iterdir():
        if not p.name.endswith(OLD_SUFFIX):
            continue
        if p.name[:-len(OLD_SUFFIX)].casefold() not in PACKAGE_FILES | PACKAGE_DIRS:
            continue  # never remove a player's own *.old backups
        for _ in range(CLEAN_WAIT):
            try:
                shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
                n += 1
                break
            except PermissionError:
                time.sleep(1)
    shutil.rmtree(game / "update", ignore_errors=True)
    emit("cleaned", n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    host = "windows" if os.name == "nt" else "linux"
    c = sub.add_parser("check")
    c.add_argument("--version", required=True, help="this program's (rt_port_version)")
    c.add_argument("--os", choices=ASSET_SUFFIX, default=host)
    f = sub.add_parser("fetch")
    f.add_argument("--tag", required=True)
    f.add_argument("--dest", type=Path, required=True, help="where the download goes (next to what it replaces)")
    f.add_argument("--os", choices=ASSET_SUFFIX, default=host)
    k = sub.add_parser("clean")
    k.add_argument("--game", type=Path, required=True)
    args = ap.parse_args()
    try:
        {"check": check, "fetch": fetch, "clean": clean}[args.cmd](args)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, urllib.error.URLError) as e:
        emit("error", args.cmd, str(e).replace("\n", " "))
        sys.exit(1)


if __name__ == "__main__":
    main()
