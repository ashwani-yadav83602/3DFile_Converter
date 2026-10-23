"""JT binary inspection helpers for probing embedded material colors."""

import re
import struct
import zlib
from collections import Counter


JT_END_GUID = b"\xff" * 16
JT_MATERIAL_GUID_STR = "10dd1030-2ac8-11d1-9b6b-0080c7bb2597"
# The same GUID as it is stored on disk (first three fields little-endian)
JT_MATERIAL_GUID = struct.pack("<IHH", 0x10DD1030, 0x2AC8, 0x11D1) + bytes.fromhex("9b6b0080c7bb2597")

JT_ELEMENT_NAMES = {
    "10dd1030-2ac8-11d1-9b6b-0080c7bb2597": "Material Attribute  <-- COLORS",
    "10dd101b-2ac8-11d1-9b6b-0080c7bb2597": "Group Node",
    "10dd102a-2ac8-11d1-9b6b-0080c7bb2597": "Instance Node",
    "10dd1083-2ac8-11d1-9b6b-0080c7bb2597": "Geometric Transform Attribute",
    "ce357244-38fb-11d1-a506-0060971bdc6d": "Part Node",
    "ce357245-38fb-11d1-a506-0060971bdc6d": "Meta Data Node",
    "ce357249-38fb-11d1-a506-0060971bdc6d": "Partition Node",
}
JT_SEGMENT_TYPES = {1: "Logical Scene Graph", 2: "JT B-Rep", 3: "PMI Data", 4: "Meta Data",
                    6: "Shape", 17: "Shape LOD", 18: "Shape LOD"}


def _guid_str(b):
    d1, d2, d3 = struct.unpack("<IHH", b[:8])
    return f"{d1:08x}-{d2:04x}-{d3:04x}-{b[8:10].hex()}-{b[10:16].hex()}"


def _hexdump(b, width=16, limit=96):
    b = bytes(b[:limit])
    return "\n".join(f"    {i:04x}  {b[i:i + width].hex(' ')}" for i in range(0, len(b), width))


def _color_candidates(body):
    """Places where 4 consecutive little-endian floats all lie in [0, 1] (possible RGBA colors)."""
    found, last_end = [], -1
    body = bytes(body)
    for i in range(0, len(body) - 15):
        if i < last_end:
            continue
        r, g, b, a = struct.unpack_from("<4f", body, i)
        if all(0.0 <= v <= 1.0001 for v in (r, g, b, a)) and max(r, g, b) > 0.001 and a > 0.001:
            found.append((i, tuple(round(v, 3) for v in (r, g, b, a))))
            last_end = i + 16
    return found


def _inflate_any(payload):
    for off in range(0, min(len(payload) - 2, 64)):
        if payload[off] == 0x78 and payload[off + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                out = zlib.decompressobj().decompress(payload[off:])
                if out:
                    return out
            except zlib.error:
                continue
    return None


def _structured_probe(data, say):
    """Read header, table of contents and the scene-graph segment the way the JT spec describes."""
    m = re.search(rb"Version\s+(\d+)\.(\d+)", data[:80])
    if not m:
        say("Header: no 'Version x.y' text found - this may not be a JT file.")
        return
    major, minor = int(m.group(1)), int(m.group(2))
    byte_order = data[80]
    pos = 85  # 80 version + 1 byte order + 4 reserved
    if major >= 10:
        toc_offset = struct.unpack_from("<q", data, pos)[0]
        pos += 8
    else:
        toc_offset = struct.unpack_from("<i", data, pos)[0]
        pos += 4
    lsg_guid = _guid_str(data[pos:pos + 16])
    say(f"JT version {major}.{minor}, byte order {'little-endian' if byte_order == 0 else 'BIG-ENDIAN'}, TOC offset {toc_offset}")
    if byte_order != 0:
        say("Big-endian files are not handled by this probe.")
        return

    count = struct.unpack_from("<i", data, toc_offset)[0]
    pos = toc_offset + 4
    entries = []
    for _ in range(count):
        gid = _guid_str(data[pos:pos + 16])
        pos += 16
        if major >= 10:
            off = struct.unpack_from("<q", data, pos)[0]
            pos += 8
        else:
            off = struct.unpack_from("<i", data, pos)[0]
            pos += 4
        length, attrs = struct.unpack_from("<II", data, pos)
        pos += 8
        entries.append({"guid": gid, "offset": off, "length": length, "type": attrs >> 24})
    say(f"Segments: {len(entries)}")
    for t, n in sorted(Counter(e["type"] for e in entries).items()):
        say(f"  type {t:>3} {JT_SEGMENT_TYPES.get(t, 'other'):<22} x{n}")

    lsg = next((e for e in entries if e["guid"] == lsg_guid), None) or next((e for e in entries if e["type"] == 1), None)
    if lsg is None:
        say("No Logical Scene Graph segment found.")
        return
    payload = data[lsg["offset"] + 24: lsg["offset"] + max(lsg["length"], 24)]
    buf = _inflate_any(payload) or payload
    say(f"Scene-graph segment: {len(buf):,} bytes")

    counts, pos = Counter(), 0
    while pos + 20 <= len(buf):
        elen = struct.unpack_from("<i", buf, pos)[0]
        if elen < 16 or pos + 4 + elen > len(buf):
            break
        g = buf[pos + 4: pos + 20]
        if g != JT_END_GUID:
            counts[_guid_str(g)] += 1
        pos += 4 + elen
    say(f"Scene-graph elements: {sum(counts.values())}")
    for g, n in counts.most_common(15):
        say(f"  x{n:<5} {g}  {JT_ELEMENT_NAMES.get(g, '')}")
    say(f"Material Attribute elements in scene graph: {counts.get(JT_MATERIAL_GUID_STR, 0)}")


def _scan_probe(data, say):
    """Independent check: inflate every zlib stream in the file and look for Material Attribute GUIDs."""
    mv = memoryview(data)
    tried = inflated = hits = shown = 0
    colors = Counter()
    for m in re.finditer(rb"\x78[\x01\x5e\x9c\xda]", data):
        tried += 1
        if tried > 50000:
            say("(stopped scanning after 50000 candidate streams)")
            break
        try:
            chunk = zlib.decompressobj().decompress(mv[m.start(): m.start() + 4_000_000], 16_000_000)
        except zlib.error:
            continue
        if len(chunk) < 20:
            continue
        inflated += 1
        pos = 0
        while True:
            i = chunk.find(JT_MATERIAL_GUID, pos)
            if i < 0:
                break
            hits += 1
            body = chunk[i + 16: i + 16 + 120]
            cands = _color_candidates(body)
            for _, c in cands:
                colors[c] += 1
            if shown < 3:
                say(f"  Material data #{hits} (120 bytes after the GUID):")
                say(_hexdump(body, limit=120))
                say(f"    RGBA-looking values: {cands[:5]}")
                shown += 1
            pos = i + 16
    say(f"Scan: {tried} candidate streams, {inflated} inflated, Material Attribute GUID found {hits} times")
    if colors:
        say(f"Distinct RGBA-looking values near those GUIDs: {len(colors)}")
        for c, n in colors.most_common(15):
            say(f"  RGBA {c}  x{n}")


def probe_jt(data: bytes) -> list:
    out = []
    say = out.append
    say(f"File size: {len(data):,} bytes")
    say("First 96 bytes: " + data[:96].hex(" "))
    say("")
    say("== Structured read (header / table of contents / scene graph) ==")
    try:
        _structured_probe(data, say)
    except Exception as e:
        say(f"Structured read failed: {type(e).__name__}: {e}")
    say("")
    say("== Brute-force scan of all compressed data ==")
    try:
        _scan_probe(data, say)
    except Exception as e:
        say(f"Scan failed: {type(e).__name__}: {e}")
    return out
