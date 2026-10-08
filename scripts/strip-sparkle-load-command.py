#!/usr/bin/env python3
"""Adjust load commands in the Chinese build's executable.

Sparkle is compiled out and its framework is deleted, so its load command has
to go too. libswiftCoreAudio is linked weakly, matching the official app: a
strong link makes dyld abort when that dylib has no CocoaError._nsError symbol.
"""

import struct
import sys

MH_MAGIC_64 = 0xFEEDFACF
FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
LC_LOAD_DYLIB = 0xC
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_REEXPORT_DYLIB = 0x8000001F
LC_LAZY_LOAD_DYLIB = 0x20
LC_LOAD_UPWARD_DYLIB = 0x80000023
DYLIB_COMMANDS = {
    LC_LOAD_DYLIB,
    LC_LOAD_WEAK_DYLIB,
    LC_REEXPORT_DYLIB,
    LC_LAZY_LOAD_DYLIB,
    LC_LOAD_UPWARD_DYLIB,
}


def dylib_name(blob):
    if len(blob) < 24:
        return b""
    name_off = struct.unpack_from("<I", blob, 8)[0]
    if name_off >= len(blob):
        return b""
    return blob[name_off:].split(b"\x00", 1)[0]


def adjust_slice(data, start):
    """Drop Sparkle and force a single weak libswiftCoreAudio load command.

    Returns (sparkle commands removed, core audio commands weakened or deduped).
    """
    magic = struct.unpack_from("<I", data, start)[0]
    if magic != MH_MAGIC_64:
        raise SystemExit(f"unsupported mach-o slice at {start:#x} (magic {magic:#x})")
    ncmds, sizeofcmds = struct.unpack_from("<II", data, start + 16)
    offset = start + 32
    end = offset + sizeofcmds
    kept = bytearray()
    removed = 0
    weakened = 0
    seen_core_audio = False
    for _ in range(ncmds):
        if offset + 8 > end:
            raise SystemExit("load commands ran past sizeofcmds")
        cmd, cmdsize = struct.unpack_from("<II", data, offset)
        if cmdsize < 8 or offset + cmdsize > end:
            raise SystemExit(f"bad load command size {cmdsize} at {offset:#x}")
        blob = bytearray(data[offset:offset + cmdsize])
        name = dylib_name(blob) if cmd in DYLIB_COMMANDS else b""
        if b"Sparkle.framework" in name:
            removed += 1
        elif b"libswiftCoreAudio.dylib" in name:
            if seen_core_audio:
                weakened += 1
            else:
                seen_core_audio = True
                if cmd != LC_LOAD_WEAK_DYLIB:
                    struct.pack_into("<I", blob, 0, LC_LOAD_WEAK_DYLIB)
                    weakened += 1
                kept += blob
        else:
            kept += blob
        offset += cmdsize
    if len(kept) == sizeofcmds and weakened == 0 and removed == 0:
        return 0, 0
    if len(kept) > sizeofcmds:
        raise SystemExit("compacted load commands grew")
    data[start + 32:start + 32 + len(kept)] = kept
    data[start + 32 + len(kept):end] = b"\x00" * (sizeofcmds - len(kept))
    count = 0
    cursor = 0
    while cursor < len(kept):
        _, cmdsize = struct.unpack_from("<II", kept, cursor)
        if cmdsize < 8 or cursor + cmdsize > len(kept):
            raise SystemExit("compacted load commands are not walkable")
        count += 1
        cursor += cmdsize
    struct.pack_into("<I", data, start + 16, count)
    struct.pack_into("<I", data, start + 20, len(kept))
    return removed, weakened


def process(data):
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic == FAT_MAGIC:
        slices = [struct.unpack_from(">I", data, 16 + i * 20)[0] for i in range(struct.unpack_from(">I", data, 4)[0])]
    elif magic == FAT_MAGIC_64:
        slices = [struct.unpack_from(">Q", data, 16 + i * 32)[0] for i in range(struct.unpack_from(">I", data, 4)[0])]
    elif struct.unpack_from("<I", data, 0)[0] == MH_MAGIC_64:
        slices = [0]
    else:
        raise SystemExit(f"unsupported mach-o magic {magic:#x}")
    removed = weakened = 0
    for start in slices:
        one_removed, one_weakened = adjust_slice(data, start)
        removed += one_removed
        weakened += one_weakened
    return removed, weakened


def _load_command(name, cmd=LC_LOAD_DYLIB):
    encoded = name.encode("ascii") + b"\x00"
    payload = 24 + len(encoded)
    cmdsize = (payload + 7) & ~7
    blob = bytearray(cmdsize)
    struct.pack_into("<III", blob, 0, cmd, cmdsize, 24)
    blob[24:24 + len(encoded)] = encoded
    return bytes(blob)


def self_test():
    sparkle = _load_command("@rpath/Sparkle.framework/Versions/B/Sparkle")
    system = _load_command("/usr/lib/libSystem.B.dylib")
    header = bytearray(32)
    struct.pack_into("<IIIIIIII", header, 0, MH_MAGIC_64, 0x0100000C, 0, 2, 2, len(sparkle) + len(system), 0, 0)
    original = header + sparkle + system + b"TAIL"
    data = bytearray(original)
    removed, weakened = process(data)
    assert (removed, weakened) == (1, 0), (removed, weakened)
    assert len(data) == len(original)
    assert data.endswith(b"TAIL")
    ncmds, sizeofcmds = struct.unpack_from("<II", data, 16)
    assert ncmds == 1, ncmds
    assert sizeofcmds == len(system), sizeofcmds
    assert dylib_name(bytes(data[32:32 + sizeofcmds])) == b"/usr/lib/libSystem.B.dylib"
    assert b"Sparkle" not in bytes(data[:32 + sizeofcmds])

    slice_bytes = bytes(original)
    # Big-endian fat header, one arm64 slice. The arch's offset field is at byte 16.
    fat = struct.pack(">II", FAT_MAGIC, 1)
    fat += struct.pack(">IIIII", 0x0100000C, 0, 8 + 20, len(slice_bytes), 14)
    fat_data = bytearray(fat + slice_bytes)
    assert process(fat_data) == (1, 0)
    assert dylib_name(bytes(fat_data[len(fat) + 32:len(fat) + 32 + len(system)])) == b"/usr/lib/libSystem.B.dylib"

    core = _load_command("/usr/lib/swift/libswiftCoreAudio.dylib")
    core_dup = _load_command("/usr/lib/swift/libswiftCoreAudio.dylib")
    header2 = bytearray(32)
    struct.pack_into("<IIIIIIII", header2, 0, MH_MAGIC_64, 0x0100000C, 0, 2, 3, len(system) + len(core) + len(core_dup), 0, 0)
    audio = bytearray(header2 + system + core + core_dup + b"TAIL")
    removed, weakened = process(audio)
    assert removed == 0 and weakened == 2, (removed, weakened)
    ncmds, sizeofcmds = struct.unpack_from("<II", audio, 16)
    assert ncmds == 2, ncmds
    cmd = struct.unpack_from("<I", audio, 32 + len(system))[0]
    assert cmd == LC_LOAD_WEAK_DYLIB, cmd
    assert audio.endswith(b"TAIL")
    print("self-test ok")


def main(argv):
    if argv[1:] == ["--self-test"]:
        self_test()
        return
    if len(argv) != 2:
        raise SystemExit(f"usage: {argv[0]} <executable>")
    path = argv[1]
    with open(path, "rb") as handle:
        data = bytearray(handle.read())
    removed, weakened = process(data)
    if removed or weakened:
        with open(path, "wb") as handle:
            handle.write(data)
    print(f"removed {removed} Sparkle load command(s); weakened {weakened} libswiftCoreAudio load command(s)")


if __name__ == "__main__":
    main(sys.argv)
