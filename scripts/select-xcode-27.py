#!/usr/bin/env python3
"""Print the newest Xcode 27 whose linker is LD 27037 or newer.

The official Compositor 1.4.6 binary was linked with LD 27037.1 against the
macOS 27.0 SDK. Xcode 27.0's linker is older and links libswiftCoreAudio
strongly, which dyld then rejects. Stdout is the chosen .app path.
"""

import re
import subprocess
import sys
from pathlib import Path

MIN_LD = (27037, 0)


def ld_version(text):
    for line in text.splitlines():
        if "PROGRAM:ld" not in line and "PROJECT:" not in line:
            continue
        nums = re.findall(r"(\d+)\.(\d+)", line)
        if nums:
            return max((int(major), int(minor)) for major, minor in nums)
    nums = [(int(major), int(minor)) for major, minor in re.findall(r"(\d+)\.(\d+)", text) if int(major) >= 1000]
    return max(nums) if nums else None


def xcode_version(path):
    match = re.search(r"Xcode_(\d+(?:\.\d+)*)", path.name)
    if not match:
        return (27, 0)
    return tuple(int(part) for part in match.group(1).split("."))


def main():
    seen = set()
    found = []
    apps = sorted(Path("/Applications").glob("Xcode_27*.app"))
    if not apps:
        raise SystemExit("no Xcode 27 is installed")
    for app in apps:
        real = app.resolve()
        if real in seen:
            continue
        seen.add(real)
        ld = real / "Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/ld"
        if not ld.is_file():
            print(f"{app}: no ld", file=sys.stderr)
            continue
        out = subprocess.check_output([str(ld), "-v"], stderr=subprocess.STDOUT, text=True, errors="replace")
        version = ld_version(out)
        sdk = real / "Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX27.0.sdk"
        print(f"=== {app} -> {real} ===", file=sys.stderr)
        print(out, file=sys.stderr)
        print(f"parsed ld {version}, macosx27.0 sdk {sdk.is_dir()}", file=sys.stderr)
        found.append((xcode_version(app), version, sdk.is_dir(), str(real)))

    eligible = [item for item in found if item[1] is not None and item[1] >= MIN_LD and item[2]]
    if not eligible:
        raise SystemExit("no Xcode 27 has ld >= 27037 and the macOS 27.0 SDK")
    eligible.sort()
    chosen = eligible[-1]
    print(f"chosen {chosen[3]} ld {chosen[1][0]}.{chosen[1][1]}", file=sys.stderr)
    print(chosen[3])


if __name__ == "__main__":
    main()
