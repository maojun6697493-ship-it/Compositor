#!/usr/bin/env python3
"""Remove Sparkle's load command from a Mach-O executable.

The Chinese build compiles Sparkle out, then deletes Sparkle.framework. dyld
would still abort at launch if the executable kept LC_LOAD_DYLIB for it.
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


def strip_slice(data, start):
    magic = struct.unpack_from("<I", data, start)[0]
    if magic != MH_MAGIC_64:
        raise SystemExit(f"unsupported mach-o slice at {start:#x} (magic {magic:#x})")
    ncmds, sizeofcmds = struct.unpack_from("<II", data, start + 16)
    offset = start + 32
    end = offset + sizeofcmds
    kept = bytearray()
    removed = 0
    for _ in range(ncmds):
        if offset + 8 > end:
            raise SystemExit("load commands ran past sizeofcmds")
        cmd, cmdsize = struct.unpack_from("<II", data, offset)
        if cmdsize < 8 or offset + cmdsize > end:
            raise SystemExit(f"bad load command size {cmdsize} at {offset:#x}")
        blob = bytes(data[offset:offset + cmdsize])
        name = dylib_name(blob) if cmd in DYLIB_COMMANDS else b""
        if b"Sparkle.framework" in name:
            removed += 1
        else:
            kept += blob
        offset += cmdsize
    if removed == 0:
        return 0
    if len(kept) > sizeofcmds:
        raise SystemExit("compacted load commands grew")
    data[start + 32:start + 32 + len(kept)] = kept
    data[start + 32 + len(kept):end] = b"\x00" * (sizeofcmds - len(kept))
    struct.pack_into("<I", data, start + 16, ncmds - removed)
    struct.pack_into("<I", data, start + 20, len(kept))
    return removed


def process(data):
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic == FAT_MAGIC:
        nfat = struct.unpack_from(">I", data, 4)[0]
        return sum(strip_slice(data, struct.unpack_from(">I", data, 16 + i * 20)[0]) for i in range(nfat))
    if magic == FAT_MAGIC_64:
        nfat = struct.unpack_from(">I", data, 4)[0]
        return sum(strip_slice(data, struct.unpack_from(">Q", data, 16 + i * 32)[0]) for i in range(nfat))
    if struct.unpack_from("<I", data, 0)[0] == MH_MAGIC_64:
        return strip_slice(data, 0)
    raise SystemExit(f"unsupported mach-o magic {magic:#x}")


def _load_command(name):
    encoded = name.encode("ascii") + b"\x00"
    payload = 24 + len(encoded)
    cmdsize = (payload + 7) & ~7
    blob = bytearray(cmdsize)
    struct.pack_into("<III", blob, 0, LC_LOAD_DYLIB, cmdsize, 24)
    blob[24:24 + len(encoded)] = encoded
    return bytes(blob)


def self_test():
    sparkle = _load_command("@rpath/Sparkle.framework/Versions/B/Sparkle")
    system = _load_command("/usr/lib/libSystem.B.dylib")
    header = bytearray(32)
    struct.pack_into("<IIIIIIII", header, 0, MH_MAGIC_64, 0x0100000C, 0, 2, 2, len(sparkle) + len(system), 0, 0)
    original = header + sparkle + system + b"TAIL"
    data = bytearray(original)
    removed = process(data)
    assert removed == 1, removed
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
    assert process(fat_data) == 1
    assert dylib_name(bytes(fat_data[len(fat) + 32:len(fat) + 32 + len(system)])) == b"/usr/lib/libSystem.B.dylib"
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
    removed = process(data)
    if removed:
        with open(path, "wb") as handle:
            handle.write(data)
    print(f"removed {removed} Sparkle load command(s)")


if __name__ == "__main__":
    main(sys.argv)
