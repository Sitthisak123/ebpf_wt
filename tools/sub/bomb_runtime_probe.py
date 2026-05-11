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
from tools.ballistic_layout_dumper import try_get_active_weapon, read_u64, read_u32, read_f32
from tools.sub.air_secondary_weapon_dumper import _scan_loadout_anchors


LOADOUT_PRESET_OFF = 0x7C0
LOADOUT_CHILD_ENTRY_TABLE_OFF = 0x230
ENTRY_TABLE_START_OFF = 0x50
ENTRY_TABLE_END_OFF = 0x110
ENTRY_TABLE_STRIDE = 0x10


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


def _read_inline_ascii(scanner, ptr, size=96):
    if not mul.is_valid_ptr(ptr):
        return None
    raw = scanner.read_mem(ptr, size)
    if not raw:
        return None
    try:
        text = raw.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    if len(text) < 3 or not any(ch.isalnum() for ch in text):
        return None
    return text


def _extract_inline_strings(raw):
    out = []
    for off in range(len(raw)):
        if not (32 <= raw[off] < 127):
            continue
        if off > 0 and 32 <= raw[off - 1] < 127:
            continue
        end = off
        while end < len(raw) and 32 <= raw[end] < 127:
            end += 1
        if end - off < 3:
            continue
        if end < len(raw) and raw[end] != 0:
            continue
        try:
            text = raw[off:end].decode("utf-8", errors="ignore").strip()
        except Exception:
            text = ""
        if len(text) < 3 or not any(ch.isalnum() for ch in text):
            continue
        out.append({"off": _hex0(off), "text": text})
    return out[:24]


def _extract_float_rows(raw, start_off=0x30, row_size=0x20, rows=8):
    out = []
    for i in range(rows):
        off = start_off + (i * row_size)
        if off + row_size > len(raw):
            break
        vals = [struct.unpack_from("<f", raw, off + j)[0] for j in range(0, row_size, 4)]
        if not all(-5000.0 <= v <= 5000.0 for v in vals):
            continue
        if not any(abs(v) > 0.0001 for v in vals):
            continue
        out.append({"off": _hex0(off), "values": [_safe_round(v) for v in vals]})
    return out


def _summarize_object(scanner, ptr, size=0x180):
    raw = scanner.read_mem(ptr, size) or b""
    if not raw:
        return {}
    ints = []
    float_hits = []
    for off in range(0, size, 4):
        u = read_u32(scanner, ptr + off)
        if u in (1, 2, 3, 4, 5, 8, 16, 32, 33, 88, 115, 134, 161, 201, 353, 500):
            ints.append({"off": _hex0(off), "u32": int(u)})
        f = read_f32(scanner, ptr + off)
        if f is not None and any(abs(f - r) <= 0.75 for r in (2.0, 9.0, 88.0, 134.0, 201.0, 500.0)):
            float_hits.append({"off": _hex0(off), "f32": _safe_round(f)})
    return {
        "ptr": _hex0(ptr),
        "head_text": _read_inline_ascii(scanner, ptr, 96) or mul._read_c_string(scanner, ptr, 96) or "",
        "inline_strings": _extract_inline_strings(raw),
        "int_hits": ints[:32],
        "float_hits": float_hits[:16],
        "float_rows": _extract_float_rows(raw),
        "raw_hex": raw.hex(),
    }


def _extract_entry_table(scanner, entry_table_ptr):
    raw = scanner.read_mem(entry_table_ptr, 0x180) or b""
    entries = []
    for off in range(ENTRY_TABLE_START_OFF, ENTRY_TABLE_END_OFF, ENTRY_TABLE_STRIDE):
        if off + ENTRY_TABLE_STRIDE > len(raw):
            break
        ptr = struct.unpack_from("<Q", raw, off)[0]
        code_a = struct.unpack_from("<I", raw, off + 8)[0]
        code_b = struct.unpack_from("<I", raw, off + 12)[0]
        if not mul.is_valid_ptr(ptr):
            continue
        if not (0 <= code_a <= 64 and 0 <= code_b <= 64):
            continue
        entries.append({
            "off": _hex0(off),
            "ptr": _hex0(ptr),
            "code_a": int(code_a),
            "code_b": int(code_b),
            "summary": _summarize_object(scanner, ptr),
        })
    return entries


def _find_loadout_anchor(scanner, unit_ptr):
    anchors = _scan_loadout_anchors(scanner, unit_ptr)
    if not anchors:
        ptr = read_u64(scanner, unit_ptr + LOADOUT_PRESET_OFF)
        text = _read_inline_ascii(scanner, ptr, 96) or mul._read_c_string(scanner, ptr, 96) or ""
        if not ptr:
            return {}
        return {
            "unit_off": _hex0(LOADOUT_PRESET_OFF),
            "ptr": _hex0(ptr),
            "text": text,
            "summary": _summarize_object(scanner, ptr, size=0x240),
            "child_objects": [],
        }
    anchors.sort(key=lambda a: (-int("bomb" in str(a.get("text") or "").lower()), -int(a.get("score") or 0), a.get("unit_off", "0x0")))
    best = anchors[0]
    return {
        "unit_off": best.get("unit_off", _hex0(LOADOUT_PRESET_OFF)),
        "ptr": best.get("ptr", "0x0"),
        "text": best.get("text", ""),
        "summary": _summarize_object(scanner, int(best.get("ptr", "0x0"), 16), size=0x240) if best.get("ptr") else {},
        "child_objects": best.get("child_objects", []),
    }


def _collect_dynamic_entries(anchor):
    entries = []
    seen = set()
    for child in anchor.get("child_objects", []):
        child_ptr = child.get("ptr", "0x0")
        child_off = child.get("parent_off", "0x0")
        for rec in child.get("ptr_code_entries", []) or []:
            key = (rec.get("ptr"), rec.get("code_a"), rec.get("code_b"))
            if key in seen:
                continue
            seen.add(key)
            item = dict(rec)
            item["parent_off"] = child_off
            item["parent_ptr"] = child_ptr
            entries.append(item)
    return entries


def _classify_entries(entries):
    twin_profiles = []
    count_blocks = []
    other = []
    for e in entries:
        code = (e["code_a"], e["code_b"])
        ptr = e["ptr"]
        summary = e.get("summary") or {}
        if code == (5, 5):
            twin_profiles.append(e)
        elif code == (4, 4):
            ints = {(x["off"], x["u32"]) for x in summary.get("int_hits", [])}
            if any(v == 2 for _, v in ints):
                count_blocks.append(e)
            else:
                other.append(e)
        else:
            other.append(e)
    return twin_profiles, count_blocks, other


def _derive_slot_hypothesis(count_blocks):
    out = []
    for e in count_blocks:
        ints = {x["off"]: x["u32"] for x in e.get("summary", {}).get("int_hits", [])}
        pairs = []
        for a, b in (("0xc0", "0xc4"), ("0xc4", "0xc8"), ("0x110", "0x114"), ("0x114", "0x118")):
            if a in ints and b in ints:
                pairs.append({"left_off": a, "left": ints[a], "right_off": b, "right": ints[b], "sum": ints[a] + ints[b]})
        if pairs:
            out.append({"ptr": e["ptr"], "code": (e["code_a"], e["code_b"]), "pairs": pairs})
    return out


def render_text(payload):
    lines = []
    lines.append("=" * 58)
    lines.append(" BOMB RUNTIME PROBE")
    lines.append("=" * 58)
    lines.append(f"PID={payload['pid']} base={payload['base']} unit={payload['unit_ptr']}")
    lines.append(f"unit_key={payload['unit_key']} short_name={payload['short_name']} family={payload['family']}")
    anchor = payload.get("loadout_anchor") or {}
    lines.append(f"loadout_anchor={anchor.get('ptr','0x0')} text={anchor.get('text','')}")
    lines.append(f"entry_table={payload.get('entry_table_ptr','0x0')} entries={len(payload.get('entries',[]))}")
    lines.append("")
    lines.append("[anchor-children]")
    for idx, child in enumerate((anchor.get("child_objects") or [])[:8]):
        inline = ", ".join(x.get("text","") for x in (child.get("inline_strings") or [])[:4])
        lines.append(
            f"  [{idx}] parent_off={child.get('parent_off')} ptr={child.get('ptr')} "
            f"head={child.get('head_text') or '-'} entries={len(child.get('ptr_code_entries') or [])}"
        )
        if inline:
            lines.append(f"      inline_strings: {inline}")
    lines.append("")
    lines.append("[twin-payload-profiles]")
    for idx, e in enumerate(payload.get("twin_profiles", [])):
        lines.append(f"  [{idx}] ptr={e['ptr']} code=({e['code_a']},{e['code_b']}) head={e['summary'].get('head_text') or '-'}")
        for row in e["summary"].get("float_rows", [])[:4]:
            joined = ", ".join(f"{v:g}" for v in row["values"])
            lines.append(f"      float_row[{row['off']}]: {joined}")
        if e["summary"].get("int_hits"):
            joined = ", ".join(f"{x['u32']}@{x['off']}" for x in e["summary"]["int_hits"][:8])
            lines.append(f"      ints: {joined}")
    lines.append("")
    lines.append("[count-block-candidates]")
    for idx, e in enumerate(payload.get("count_blocks", [])):
        lines.append(f"  [{idx}] ptr={e['ptr']} code=({e['code_a']},{e['code_b']}) head={e['summary'].get('head_text') or '-'}")
        if e["summary"].get("inline_strings"):
            joined = ", ".join(f"{x['text']}@{x['off']}" for x in e["summary"]["inline_strings"][:6])
            lines.append(f"      inline_strings: {joined}")
        if e["summary"].get("int_hits"):
            joined = ", ".join(f"{x['u32']}@{x['off']}" for x in e["summary"]["int_hits"][:12])
            lines.append(f"      int_hits: {joined}")
        if e["summary"].get("float_rows"):
            for row in e["summary"]["float_rows"][:4]:
                joined = ", ".join(f"{v:g}" for v in row["values"])
                lines.append(f"      float_row[{row['off']}]: {joined}")
    lines.append("")
    lines.append("[slot-occupancy-hypothesis]")
    for idx, item in enumerate(payload.get("slot_hypothesis", [])):
        lines.append(f"  [{idx}] ptr={item['ptr']} code={item['code']}")
        for pair in item["pairs"]:
            lines.append(
                f"      {pair['left_off']}={pair['left']} | {pair['right_off']}={pair['right']} | sum={pair['sum']}"
            )
    lines.append("")
    lines.append("[other-entries]")
    for idx, e in enumerate(payload.get("other_entries", [])[:8]):
        lines.append(f"  [{idx}] ptr={e['ptr']} code=({e['code_a']},{e['code_b']}) head={e['summary'].get('head_text') or '-'}")
    return "\n".join(lines).rstrip() + "\n"


def main():
    print("\n" + "=" * 55)
    print("🚀 [SYSTEM BOOT] กำลังสแกนหา Bomb Runtime...")
    print("=" * 55)

    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    if not pid or not base_addr:
        raise RuntimeError("game process/base not found")

    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    unit_ptr, _weapon_ptr, _weapon_source, _scan_notes = try_get_active_weapon(scanner, base_addr)
    profile = mul.get_unit_filter_profile(scanner, unit_ptr) or {}
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}

    anchor = _find_loadout_anchor(scanner, unit_ptr)
    anchor_ptr = int(anchor.get("ptr", "0x0"), 16) if anchor else 0
    entry_table_ptr = read_u64(scanner, anchor_ptr + LOADOUT_CHILD_ENTRY_TABLE_OFF) if anchor_ptr else 0
    entries = _extract_entry_table(scanner, entry_table_ptr) if entry_table_ptr else []
    dynamic_entries = _collect_dynamic_entries(anchor) if anchor else []
    if dynamic_entries:
        entries = dynamic_entries
        entry_table_ptr = 0
    twin_profiles, count_blocks, other_entries = _classify_entries(entries)
    slot_hypothesis = _derive_slot_hypothesis(count_blocks)

    payload = {
        "generated_at": datetime.now().isoformat(),
        "pid": pid,
        "base": _hex0(base_addr),
        "unit_ptr": _hex0(unit_ptr),
        "unit_key": str(dna.get("name_key") or profile.get("unit_key") or ""),
        "short_name": str(dna.get("short_name") or profile.get("short_name") or ""),
        "family": str(dna.get("family") or profile.get("tag") or ""),
        "loadout_anchor": anchor,
        "entry_table_ptr": _hex0(entry_table_ptr),
        "entries": entries,
        "twin_profiles": twin_profiles,
        "count_blocks": count_blocks,
        "slot_hypothesis": slot_hypothesis,
        "other_entries": other_entries,
    }

    os.makedirs(os.path.join(PROJECT_ROOT, "dumps"), exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(PROJECT_ROOT, "dumps", f"bomb_runtime_probe_{stamp}.json")
    txt_path = os.path.join(PROJECT_ROOT, "dumps", f"bomb_runtime_probe_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(render_text(payload))

    print("\n" + "=" * 58)
    print(" BOMB RUNTIME PROBE")
    print("=" * 58)
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")


if __name__ == "__main__":
    main()
