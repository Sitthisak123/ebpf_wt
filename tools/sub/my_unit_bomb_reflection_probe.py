#!/usr/bin/env python3
import json
import os
import struct
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_base_address, get_game_pid, init_dynamic_offsets
import src.utils.mul as mul


START_OFF = 0x7C0
END_OFF = 0xB80
STRIDE = 0x8
NEIGHBOR_BACK = 0x20
NEIGHBOR_FWD = 0x80
PROBE_MATCH_TERMS = (
    "bomb",
    "rocket",
    "torpedo",
    "weapon",
    "trigger",
    "slot",
    "support",
    "reload",
    "fuse",
    "delay",
    "activation",
    "series",
)
INT_HITS = {0, 1, 2, 3, 4, 5, 6, 8, 9, 13, 16, 32, 33, 64, 79, 88, 97, 114, 134, 201, 250, 500}
FLOAT_TARGETS = (1.0, 2.0, 3.0, 5.0, 6.0, 9.0, 16.0, 79.0, 88.0, 97.0, 114.0, 134.0, 201.0, 250.0, 500.0)


def _hex0(v):
    try:
        return hex(int(v or 0))
    except Exception:
        return "0x0"


def _safe_round(v, nd=6):
    try:
        return round(float(v), nd)
    except Exception:
        return 0.0


def _read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def _read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return None
    return struct.unpack("<I", raw)[0]


def _read_i32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return None
    return struct.unpack("<i", raw)[0]


def _read_f32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return None
    return struct.unpack("<f", raw)[0]


def _looks_like_ptr(ptr):
    return ptr >= 0x100000 and mul.is_valid_ptr(ptr)


def _read_inline_ascii(scanner, ptr, size=128):
    if not _looks_like_ptr(ptr):
        return ""
    raw = scanner.read_mem(ptr, size)
    if not raw:
        return ""
    try:
        text = raw.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""
    if len(text) < 2 or not any(ch.isalnum() for ch in text):
        return ""
    return text


def _extract_inline_strings(raw, min_len=3, limit=8):
    out = []
    for off in range(len(raw)):
        if not (32 <= raw[off] < 127):
            continue
        if off > 0 and 32 <= raw[off - 1] < 127:
            continue
        end = off
        while end < len(raw) and 32 <= raw[end] < 127:
            end += 1
        if end - off < min_len:
            continue
        if end < len(raw) and raw[end] != 0:
            continue
        try:
            text = raw[off:end].decode("utf-8", errors="ignore").strip()
        except Exception:
            continue
        if not any(ch.isalnum() for ch in text):
            continue
        out.append({"off": _hex0(off), "text": text})
        if len(out) >= limit:
            break
    return out


def _score_field_name(text):
    blob = str(text or "").lower()
    score = 0
    for key in PROBE_MATCH_TERMS:
        if key in blob:
            score += 6
    return score


def _summarize_object(scanner, ptr, size=0x140):
    if not _looks_like_ptr(ptr):
        return {}
    raw = scanner.read_mem(ptr, size) or b""
    if not raw:
        return {}
    head = _read_inline_ascii(scanner, ptr, 96) or mul._read_c_string(scanner, ptr, 96) or ""
    ints = []
    floats = []
    for off in range(0, min(size, 0x100), 4):
        u = _read_u32(scanner, ptr + off)
        if u in INT_HITS:
            ints.append({"off": _hex0(off), "u32": int(u)})
        f = _read_f32(scanner, ptr + off)
        if f is not None and -100000.0 <= f <= 100000.0:
            if any(abs(f - target) <= 0.75 for target in FLOAT_TARGETS):
                floats.append({"off": _hex0(off), "f32": _safe_round(f)})
    return {
        "ptr": _hex0(ptr),
        "head_text": head,
        "inline_strings": _extract_inline_strings(raw, min_len=3, limit=8),
        "int_hits": ints[:16],
        "float_hits": floats[:16],
    }


def _collect_neighbors(scanner, unit_ptr, center_off):
    start = max(0, center_off - NEIGHBOR_BACK)
    end = center_off + NEIGHBOR_FWD
    hits = []
    for off in range(start, end, 4):
        addr = unit_ptr + off
        u32 = _read_u32(scanner, addr)
        i32 = _read_i32(scanner, addr)
        f32 = _read_f32(scanner, addr)
        ptr = _read_u64(scanner, addr) if (off % 8 == 0) else 0
        text = _read_inline_ascii(scanner, ptr, 96) or mul._read_c_string(scanner, ptr, 96) if ptr else ""
        score = 0
        if u32 in INT_HITS:
            score += 2
        if f32 is not None and -100000.0 <= f32 <= 100000.0 and any(abs(f32 - target) <= 0.75 for target in FLOAT_TARGETS):
            score += 3
        if text:
            score += _score_field_name(text)
        if score <= 0:
            continue
        hits.append({
            "off": _hex0(off),
            "u32": int(u32) if u32 is not None else None,
            "i32": int(i32) if i32 is not None else None,
            "f32": _safe_round(f32) if f32 is not None else None,
            "ptr": _hex0(ptr) if ptr else "0x0",
            "text": text,
            "score": score,
        })
    hits.sort(key=lambda x: (-x["score"], x["off"]))
    return hits[:24]


def _scan_named_fields(scanner, unit_ptr):
    fields = []
    for off in range(START_OFF, END_OFF, STRIDE):
        ptr = _read_u64(scanner, unit_ptr + off)
        if not _looks_like_ptr(ptr):
            continue
        text = _read_inline_ascii(scanner, ptr, 128) or mul._read_c_string(scanner, ptr, 128) or ""
        score = _score_field_name(text)
        if score <= 0:
            continue
        summary = _summarize_object(scanner, ptr)
        neighbors = _collect_neighbors(scanner, unit_ptr, off)
        fields.append({
            "unit_off": _hex0(off),
            "ptr": _hex0(ptr),
            "field_name": text,
            "score": score,
            "object_summary": summary,
            "neighbors": neighbors,
        })
    fields.sort(key=lambda x: (-x["score"], x["unit_off"]))
    return fields


def render_text(payload):
    lines = []
    lines.append("=" * 58)
    lines.append(" MY UNIT BOMB REFLECTION PROBE")
    lines.append("=" * 58)
    lines.append(f"PID={payload['pid']} base={payload['base']} unit={payload['unit_ptr']}")
    lines.append(f"unit_key={payload['unit_key']} short_name={payload['short_name']} family={payload['family']}")
    lines.append(f"range={payload['scan_range']}")
    lines.append("")
    lines.append("[named-fields]")
    for idx, row in enumerate(payload.get("named_fields", [])[:24]):
        lines.append(
            f"  [{idx}] off={row['unit_off']} ptr={row['ptr']} score={row['score']} "
            f"name={row['field_name']}"
        )
        summary = row.get("object_summary") or {}
        inline = ", ".join(x.get("text", "") for x in summary.get("inline_strings", [])[:5])
        if inline:
            lines.append(f"      inline_strings: {inline}")
        ints = ", ".join(f"{x['u32']}@{x['off']}" for x in summary.get("int_hits", [])[:8])
        if ints:
            lines.append(f"      int_hits: {ints}")
        floats = ", ".join(f"{x['f32']}@{x['off']}" for x in summary.get("float_hits", [])[:8])
        if floats:
            lines.append(f"      float_hits: {floats}")
        for hit in row.get("neighbors", [])[:10]:
            lines.append(
                f"      near {hit['off']}: u32={hit['u32']} f32={hit['f32']} "
                f"ptr={hit['ptr']} text={hit['text'] or '-'} score={hit['score']}"
            )
    return "\n".join(lines).rstrip() + "\n"


def main():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    if not pid or not base_addr:
        raise RuntimeError("game process/base not found")

    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)
    unit_ptr, _my_team = mul.get_local_team(scanner, base_addr)
    if not unit_ptr:
        raise RuntimeError("local unit not found")
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}

    payload = {
        "generated_at": datetime.now().isoformat(),
        "pid": pid,
        "base": _hex0(base_addr),
        "unit_ptr": _hex0(unit_ptr),
        "unit_key": str(dna.get("name_key") or ""),
        "short_name": str(dna.get("short_name") or ""),
        "family": str(dna.get("family") or ""),
        "scan_range": {"start": _hex0(START_OFF), "end": _hex0(END_OFF), "stride": _hex0(STRIDE)},
        "named_fields": _scan_named_fields(scanner, unit_ptr),
    }

    os.makedirs(os.path.join(PROJECT_ROOT, "dumps"), exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(PROJECT_ROOT, "dumps", f"my_unit_bomb_reflection_probe_{stamp}.json")
    txt_path = os.path.join(PROJECT_ROOT, "dumps", f"my_unit_bomb_reflection_probe_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(render_text(payload))

    print("\n" + "=" * 58)
    print(" MY UNIT BOMB REFLECTION PROBE")
    print("=" * 58)
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")


if __name__ == "__main__":
    main()
