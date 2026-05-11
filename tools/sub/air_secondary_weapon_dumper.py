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
from tools.ballistic_layout_dumper import (
    read_u64,
    read_u32,
    read_f32,
    is_plausible_weapon_block,
    scan_weapon_ptr_candidates,
    try_get_active_weapon,
)

GUN_BULLET_LIST_PTR_OFF = 0x358
GUN_BULLET_LIST_COUNT_OFF = 0xA0
GUN_BULLET_SLOT_BASE_OFF = 0xA8
GUN_BULLET_SLOT_STRIDE = 0xA0
GUN_CURRENT_BULLET_TYPE_OFF = 0x584
SLOT_SCAN_FLOAT_MAX = 0xA0
MAX_SLOT_COUNT = 64
UNIT_STRING_SCAN_MAX = 0x2000
BOMB_KEYWORDS = ("fab", "bomb", "rocket", "missile", "weapon", "susp", "load", "rack", "pylon")


def _read_ptr(scanner, addr):
    return read_u64(scanner, addr)


def _read_u16(scanner, addr):
    raw = scanner.read_mem(addr, 2)
    if not raw or len(raw) < 2:
        return 0
    return struct.unpack("<H", raw)[0]


def _safe_round(v, nd=6):
    try:
        return round(float(v), nd)
    except Exception:
        return 0.0


def _hex0(v):
    try:
        return hex(int(v or 0))
    except Exception:
        return "0x0"


def _uniq_keep(items):
    out = []
    seen = set()
    for item in items:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _looks_texty(text):
    t = str(text or "").strip()
    return len(t) >= 3 and any(ch.isalnum() for ch in t)


def _string_score(text):
    t = str(text or "").lower()
    score = 0
    if "bomb" in t:
        score += 8
    if any(k in t for k in ("rocket", "missile", "agm", "gbu", "fab", "mk_", "mk-", "ofab", "s-")):
        score += 4
    if any(k in t for k in ("weapon", "loadout", "secondary", "suspension", "preset")):
        score += 2
    return score


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
    if len(text) < 3:
        return None
    if not any(ch.isalnum() for ch in text):
        return None
    return text


def _extract_inline_strings_from_raw(raw, step=1, min_len=3):
    out = []
    seen = set()
    n = len(raw)
    for off in range(0, n):
        b0 = raw[off]
        if not (32 <= b0 < 127):
            continue
        if off > 0 and 32 <= raw[off - 1] < 127:
            continue
        end = off
        while end < n and 32 <= raw[end] < 127:
            end += 1
        if end - off < min_len:
            continue
        # Prefer null-terminated or boundary-adjacent strings to reduce noise.
        if end < n and raw[end] not in (0,):
            continue
        text = raw[off:end].decode("utf-8", errors="ignore").strip()
        if not _looks_texty(text):
            continue
        key = (off, text)
        if key in seen:
            continue
        seen.add(key)
        out.append({"off": _hex0(off), "text": text, "score": _string_score(text)})
    out.sort(key=lambda x: (int(x["off"], 16), -x["score"], x["text"]))
    return out


def _scan_object_scalars(scanner, obj_ptr, size=0x240):
    ints = []
    floats = []
    for off in range(0, size, 4):
        u32 = read_u32(scanner, obj_ptr + off)
        if 0 < u32 <= 512:
            ints.append({"off": _hex0(off), "u32": int(u32)})
        f32 = read_f32(scanner, obj_ptr + off)
        if f32 is not None and 0.001 <= abs(f32) <= 5000.0:
            if any(abs(f32 - ref) <= 0.6 for ref in (2.0, 9.0, 88.0, 134.0, 201.0, 500.0)):
                floats.append({"off": _hex0(off), "f32": _safe_round(f32)})
    return _uniq_keep(ints[:32]), _uniq_keep(floats[:32])


def _extract_slot_like_records(raw, base_off=0x100, stride=0x20):
    records = []
    for off in range(base_off, max(base_off, len(raw) - stride + 1), stride):
        chunk = raw[off:off + stride]
        if len(chunk) < stride:
            continue
        tag = struct.unpack_from("<I", chunk, 0)[0]
        text_bytes = chunk[8:24].split(b"\x00", 1)[0]
        try:
            text = text_bytes.decode("utf-8", errors="ignore").strip()
        except Exception:
            text = ""
        if not _looks_texty(text):
            continue
        f0 = struct.unpack_from("<f", chunk, 24)[0]
        f1 = struct.unpack_from("<f", chunk, 28)[0]
        records.append({
            "off": _hex0(off),
            "tag_u32": int(tag),
            "text": text,
            "f0": _safe_round(f0),
            "f1": _safe_round(f1),
            "score": _string_score(text),
        })
    return records


def _extract_named_stride_records(raw, start_off=0x0, stride=0x20, end_off=None):
    records = []
    end = min(len(raw), end_off or len(raw))
    for off in range(start_off, end - stride + 1, stride):
        chunk = raw[off:off + stride]
        name = chunk[:16].split(b"\x00", 1)[0]
        try:
            text = name.decode("utf-8", errors="ignore").strip()
        except Exception:
            text = ""
        if not _looks_texty(text):
            continue
        tail_u32 = struct.unpack_from("<I", chunk, stride - 8)[0]
        tail_f0 = struct.unpack_from("<f", chunk, stride - 8)[0]
        tail_f1 = struct.unpack_from("<f", chunk, stride - 4)[0]
        mid_ptr = struct.unpack_from("<Q", chunk, 16)[0] if stride >= 24 else 0
        records.append({
            "off": _hex0(off),
            "text": text,
            "mid_ptr": _hex0(mid_ptr) if mid_ptr else "0x0",
            "tail_u32": int(tail_u32),
            "tail_f0": _safe_round(tail_f0),
            "tail_f1": _safe_round(tail_f1),
            "score": _string_score(text),
        })
    return records


def _summarize_object_brief(scanner, ptr):
    raw = scanner.read_mem(ptr, 0x120) or b""
    if not raw:
        return {}
    head_text = _read_inline_ascii(scanner, ptr, 96) or mul._read_c_string(scanner, ptr, 96) or ""
    inline_strings = _extract_inline_strings_from_raw(raw, min_len=3)
    ints, floats = _scan_object_scalars(scanner, ptr, 0x120)
    return {
        "ptr": _hex0(ptr),
        "head_text": head_text,
        "inline_strings": inline_strings[:8],
        "int_candidates": ints[:8],
        "float_candidates": floats[:8],
    }


def _extract_float_rows(raw, start_off=0x30, row_size=0x20, rows=6):
    out = []
    for i in range(rows):
        off = start_off + (i * row_size)
        if off + row_size > len(raw):
            break
        vals = [struct.unpack_from("<f", raw, off + j)[0] for j in range(0, row_size, 4)]
        finite = []
        ok = True
        for v in vals:
            if not (-5000.0 <= v <= 5000.0):
                ok = False
                break
            finite.append(_safe_round(v))
        if not ok:
            continue
        if not any(abs(v) > 0.0001 for v in finite):
            continue
        out.append({"off": _hex0(off), "values": finite})
    return out


def _extract_ptr_code_entries(scanner, raw, start_off=0x0, end_off=None, stride=0x10):
    entries = []
    end = min(len(raw), end_off or len(raw))
    for off in range(start_off, end - stride + 1, stride):
        ptr = struct.unpack_from("<Q", raw, off)[0]
        code_a = struct.unpack_from("<I", raw, off + 8)[0]
        code_b = struct.unpack_from("<I", raw, off + 12)[0]
        if not mul.is_valid_ptr(ptr):
            continue
        if not (0 <= code_a <= 64 and 0 <= code_b <= 64):
            continue
        summary = _summarize_object_brief(scanner, ptr)
        entries.append({
            "off": _hex0(off),
            "ptr": _hex0(ptr),
            "code_a": int(code_a),
            "code_b": int(code_b),
            "summary": summary,
        })
    return entries


def _scan_child_objects(scanner, parent_ptr, size=0x240):
    out = []
    seen_ptrs = set()
    for off in range(0, size, 8):
        child_ptr = _read_ptr(scanner, parent_ptr + off)
        if not mul.is_valid_ptr(child_ptr) or child_ptr in seen_ptrs:
            continue
        seen_ptrs.add(child_ptr)
        raw = scanner.read_mem(child_ptr, 0x180) or b""
        if not raw:
            continue
        head_text = _read_inline_ascii(scanner, child_ptr, 96) or mul._read_c_string(scanner, child_ptr, 96)
        inline_strings = _extract_inline_strings_from_raw(raw, min_len=3)
        ints, floats = _scan_object_scalars(scanner, child_ptr, 0x180)
        slot_records = _extract_slot_like_records(raw, base_off=0x0, stride=0x20)
        named_stride_records = _extract_named_stride_records(raw, start_off=0x0, stride=0x20, end_off=0x180)
        ptr_code_entries = _extract_ptr_code_entries(scanner, raw, start_off=0x20, end_off=0x120, stride=0x10)
        float_rows = _extract_float_rows(raw, start_off=0x30, row_size=0x20, rows=8)
        if not head_text and not inline_strings and not ints and not floats and not slot_records:
            continue
        out.append({
            "parent_off": _hex0(off),
            "ptr": _hex0(child_ptr),
            "head_text": head_text or "",
            "score": _string_score(head_text or "") + sum(x.get("score", 0) for x in inline_strings[:4]),
            "inline_strings": inline_strings[:16],
            "int_candidates": ints[:16],
            "float_candidates": floats[:16],
            "slot_like_records": slot_records[:12],
            "named_stride_records": named_stride_records[:12],
            "ptr_code_entries": ptr_code_entries[:16],
            "float_rows": float_rows[:8],
            "raw_hex": raw.hex(),
        })
    out.sort(key=lambda x: (-x["score"], x["parent_off"], x["ptr"]))
    return out


def _bomb_like_score(slot):
    score = 0
    mass = float(slot.get("best_mass") or 0.0)
    caliber = float(slot.get("best_caliber") or 0.0)
    count = int(slot.get("best_count") or 0)
    if mass >= 5.0:
        score += 6
    if mass >= 25.0:
        score += 6
    if caliber >= 0.05:
        score += 4
    if caliber >= 0.1:
        score += 4
    if 1 <= count <= 32:
        score += 2
    for s in slot.get("name_candidates", []):
        score += _string_score(s.get("text"))
    return score


def _scan_slot_strings(scanner, slot_base):
    out = []
    for off in range(0, GUN_BULLET_SLOT_STRIDE - 7, 8):
        ptr = _read_ptr(scanner, slot_base + off)
        if not mul.is_valid_ptr(ptr):
            continue
        text = mul._read_c_string(scanner, ptr, 96)
        if not text:
            continue
        out.append({
            "off": hex(off),
            "ptr": _hex0(ptr),
            "text": text,
            "score": _string_score(text),
        })
    out.sort(key=lambda x: (-x["score"], x["off"]))
    return _uniq_keep(out[:12])


def _scan_slot_counts(scanner, slot_base):
    out = []
    for off in range(0, GUN_BULLET_SLOT_STRIDE - 3, 4):
        u32 = read_u32(scanner, slot_base + off)
        if 0 < u32 <= 256:
            out.append({"off": hex(off), "u32": int(u32)})
    return _uniq_keep(out[:24])


def _scan_slot_floats(scanner, slot_base):
    masses = []
    calibers = []
    speeds = []
    drags = []
    misc = []
    for off in range(0, SLOT_SCAN_FLOAT_MAX - 3, 4):
        val = read_f32(scanner, slot_base + off)
        if val is None:
            continue
        if 0.005 <= val <= 2000.0:
            if 50.0 <= val <= 3000.0:
                speeds.append({"off": hex(off), "value": _safe_round(val)})
            elif 0.005 <= val <= 200.0:
                masses.append({"off": hex(off), "value": _safe_round(val)})
            if 0.001 <= val <= 0.5:
                calibers.append({"off": hex(off), "value": _safe_round(val)})
            if 0.01 <= val <= 3.0:
                drags.append({"off": hex(off), "value": _safe_round(val)})
            misc.append({"off": hex(off), "value": _safe_round(val)})
    return {
        "mass_candidates": _uniq_keep(sorted(masses, key=lambda x: (-x["value"], x["off"]))[:12]),
        "caliber_candidates": _uniq_keep(sorted(calibers, key=lambda x: (-x["value"], x["off"]))[:12]),
        "speed_candidates": _uniq_keep(sorted(speeds, key=lambda x: (-x["value"], x["off"]))[:12]),
        "drag_candidates": _uniq_keep(sorted(drags, key=lambda x: (x["value"], x["off"]))[:12]),
        "misc_float_candidates": _uniq_keep(misc[:24]),
    }


def _decode_slot(scanner, slot_base, idx):
    raw = scanner.read_mem(slot_base, GUN_BULLET_SLOT_STRIDE) or b""
    strings = _scan_slot_strings(scanner, slot_base)
    counts = _scan_slot_counts(scanner, slot_base)
    f32s = _scan_slot_floats(scanner, slot_base)
    best_mass = f32s["mass_candidates"][0]["value"] if f32s["mass_candidates"] else 0.0
    best_caliber = f32s["caliber_candidates"][0]["value"] if f32s["caliber_candidates"] else 0.0
    best_speed = f32s["speed_candidates"][0]["value"] if f32s["speed_candidates"] else 0.0
    best_drag = f32s["drag_candidates"][0]["value"] if f32s["drag_candidates"] else 0.0
    best_count = counts[0]["u32"] if counts else 0
    slot = {
        "slot_index": idx,
        "slot_base": _hex0(slot_base),
        "name_candidates": strings,
        "count_candidates": counts,
        "best_count": best_count,
        "best_mass": best_mass,
        "best_caliber": best_caliber,
        "best_speed": best_speed,
        "best_drag": best_drag,
        "mass_candidates": f32s["mass_candidates"],
        "caliber_candidates": f32s["caliber_candidates"],
        "speed_candidates": f32s["speed_candidates"],
        "drag_candidates": f32s["drag_candidates"],
        "misc_float_candidates": f32s["misc_float_candidates"],
        "raw_hex": raw.hex(),
    }
    slot["bomb_like_score"] = _bomb_like_score(slot)
    return slot


def _scan_loadout_anchors(scanner, unit_ptr):
    anchors = []
    for off in range(0, UNIT_STRING_SCAN_MAX, 8):
        ptr = _read_ptr(scanner, unit_ptr + off)
        if not mul.is_valid_ptr(ptr):
            continue
        direct = _read_inline_ascii(scanner, ptr, 96) or mul._read_c_string(scanner, ptr, 96)
        if not direct:
            continue
        if not any(k in direct.lower() for k in BOMB_KEYWORDS):
            continue

        raw = scanner.read_mem(ptr, 0x240) or b""
        ints, floats = _scan_object_scalars(scanner, ptr, 0x240)
        inline_strings = _extract_inline_strings_from_raw(raw, min_len=3)
        child_strings = []
        for sub_off in range(0, 0x240, 8):
            child_ptr = _read_ptr(scanner, ptr + sub_off)
            if not mul.is_valid_ptr(child_ptr):
                continue
            child_text = mul._read_c_string(scanner, child_ptr, 96) or _read_inline_ascii(scanner, child_ptr, 96)
            if child_text:
                child_strings.append({"off": _hex0(sub_off), "ptr": _hex0(child_ptr), "text": child_text})
        slot_like_records = _extract_slot_like_records(raw, base_off=0x100, stride=0x20)
        child_objects = _scan_child_objects(scanner, ptr, 0x240)

        anchors.append({
            "unit_off": _hex0(off),
            "ptr": _hex0(ptr),
            "text": direct,
            "score": _string_score(direct),
            "int_candidates": ints,
            "float_candidates": floats,
            "inline_strings": inline_strings[:24],
            "child_strings": _uniq_keep(child_strings[:16]),
            "slot_like_records": slot_like_records[:16],
            "child_objects": child_objects[:12],
            "raw_hex": raw.hex(),
        })
    anchors.sort(key=lambda x: (-x["score"], x["unit_off"]))
    return anchors


def _read_weapon_profile(scanner, weapon_ptr):
    profile = {
        "weapon_ptr": _hex0(weapon_ptr),
        "current_bullet_type_idx": -1,
        "bullet_list_ptr": "0x0",
        "bullet_list_count": 0,
        "slots": [],
    }
    if not mul.is_valid_ptr(weapon_ptr):
        return profile

    profile["current_bullet_type_idx"] = int((_read_u16(scanner, weapon_ptr + GUN_CURRENT_BULLET_TYPE_OFF) & 0xFF))
    bullet_list_ptr = _read_ptr(scanner, weapon_ptr + GUN_BULLET_LIST_PTR_OFF)
    profile["bullet_list_ptr"] = _hex0(bullet_list_ptr)
    if not mul.is_valid_ptr(bullet_list_ptr):
        return profile

    bullet_type_count = read_u32(scanner, bullet_list_ptr + GUN_BULLET_LIST_COUNT_OFF)
    if bullet_type_count <= 0 or bullet_type_count > MAX_SLOT_COUNT:
        return profile
    profile["bullet_list_count"] = int(bullet_type_count)

    slots = []
    for idx in range(int(bullet_type_count)):
        slot_base = bullet_list_ptr + GUN_BULLET_SLOT_BASE_OFF + (idx * GUN_BULLET_SLOT_STRIDE)
        slots.append(_decode_slot(scanner, slot_base, idx))
    profile["slots"] = sorted(slots, key=lambda x: (-x["bomb_like_score"], x["slot_index"]))
    return profile


def _scan_secondary_weapon_candidates(scanner, unit_ptr, cgame_ptr, active_weapon_ptr):
    candidates = []
    seen = {int(active_weapon_ptr or 0)}
    for source_name, base_ptr in (("unit_scan", unit_ptr), ("cgame_scan", cgame_ptr)):
        if not mul.is_valid_ptr(base_ptr):
            continue
        for cand in scan_weapon_ptr_candidates(scanner, base_ptr)[:24]:
            weapon_ptr = int(cand.get("weapon_ptr") or 0)
            if not mul.is_valid_ptr(weapon_ptr) or weapon_ptr in seen:
                continue
            seen.add(weapon_ptr)
            ok, meta = is_plausible_weapon_block(scanner, weapon_ptr)
            if not ok:
                continue
            profile = _read_weapon_profile(scanner, weapon_ptr)
            top_slot = profile["slots"][0] if profile["slots"] else {}
            candidates.append({
                "source": source_name,
                "source_off": _hex0(cand.get("source_off")),
                "weapon_ptr": _hex0(weapon_ptr),
                "meta": meta,
                "bullet_list_count": profile.get("bullet_list_count", 0),
                "current_bullet_type_idx": profile.get("current_bullet_type_idx", -1),
                "top_bomb_like_score": int(top_slot.get("bomb_like_score", 0) or 0),
                "top_name_candidates": top_slot.get("name_candidates", [])[:4],
                "top_mass": top_slot.get("best_mass", 0.0),
                "top_caliber": top_slot.get("best_caliber", 0.0),
                "top_count": top_slot.get("best_count", 0),
                "full_profile": profile,
            })
    candidates.sort(key=lambda x: (-x["top_bomb_like_score"], -x["bullet_list_count"], x["weapon_ptr"]))
    return candidates


def _render_slot(slot):
    lines = []
    lines.append(
        f"    slot[{slot['slot_index']:02d}] bomb_score={slot['bomb_like_score']} "
        f"count={slot['best_count']} mass={slot['best_mass']:.6f} "
        f"caliber={slot['best_caliber']:.6f} speed={slot['best_speed']:.3f} drag={slot['best_drag']:.6f}"
    )
    if slot.get("name_candidates"):
        joined = ", ".join(
            f"{item['text']}@{item['off']}" for item in slot["name_candidates"][:4]
        )
        lines.append(f"      names: {joined}")
    if slot.get("count_candidates"):
        joined = ", ".join(
            f"{item['u32']}@{item['off']}" for item in slot["count_candidates"][:6]
        )
        lines.append(f"      count_candidates: {joined}")
    return lines


def render_text(payload):
    lines = []
    lines.append("=" * 58)
    lines.append(" AIR SECONDARY WEAPON / BOMB DUMPER")
    lines.append("=" * 58)
    lines.append(f"PID={payload['pid']} base={payload['base']} unit={payload['unit_ptr']} cgame={payload['cgame_ptr']}")
    lines.append(
        f"unit_key={payload['unit_key']} short_name={payload['short_name']} "
        f"family={payload['family']} profile_kind={payload['profile_kind']}"
    )
    lines.append(
        f"active_weapon={payload['active_weapon_ptr']} source={payload['active_weapon_source']} "
        f"bullet_types={payload['active_profile'].get('bullet_list_count', 0)} "
        f"current_idx={payload['active_profile'].get('current_bullet_type_idx', -1)}"
    )
    lines.append("")
    lines.append("[active-slots]")
    for slot in payload["active_profile"].get("slots", [])[:16]:
        lines.extend(_render_slot(slot))
    lines.append("")
    lines.append(f"[secondary-candidates] count={len(payload['secondary_candidates'])}")
    for idx, item in enumerate(payload["secondary_candidates"][:12]):
        lines.append(
            f"  [{idx}] src={item['source']} off={item['source_off']} weapon={item['weapon_ptr']} "
            f"bullet_types={item['bullet_list_count']} top_score={item['top_bomb_like_score']} "
            f"count={item['top_count']} mass={float(item['top_mass'] or 0.0):.6f} "
            f"cal={float(item['top_caliber'] or 0.0):.6f}"
        )
        if item.get("top_name_candidates"):
            joined = ", ".join(f"{n['text']}@{n['off']}" for n in item["top_name_candidates"])
            lines.append(f"      names: {joined}")
        for slot in item["full_profile"].get("slots", [])[:6]:
            lines.extend(_render_slot(slot))
    lines.append("")
    lines.append(f"[loadout-anchors] count={len(payload.get('loadout_anchors', []))}")
    for idx, item in enumerate(payload.get("loadout_anchors", [])[:12]):
        lines.append(
            f"  [{idx}] unit_off={item['unit_off']} ptr={item['ptr']} score={item['score']} text={item['text']}"
        )
        if item.get("int_candidates"):
            joined = ", ".join(f"{x['u32']}@{x['off']}" for x in item["int_candidates"][:8])
            lines.append(f"      ints: {joined}")
        if item.get("float_candidates"):
            joined = ", ".join(f"{x['f32']}@{x['off']}" for x in item["float_candidates"][:8])
            lines.append(f"      floats: {joined}")
        if item.get("child_strings"):
            joined = ", ".join(f"{x['text']}@{x['off']}" for x in item["child_strings"][:8])
            lines.append(f"      child_strings: {joined}")
        if item.get("inline_strings"):
            joined = ", ".join(f"{x['text']}@{x['off']}" for x in item["inline_strings"][:8])
            lines.append(f"      inline_strings: {joined}")
        if item.get("slot_like_records"):
            joined = ", ".join(
                f"{x['text']}@{x['off']} tag={x['tag_u32']} f=({x['f0']},{x['f1']})"
                for x in item["slot_like_records"][:8]
            )
            lines.append(f"      slot_records: {joined}")
        for child_idx, child in enumerate(item.get("child_objects", [])[:6]):
            lines.append(
                f"      child[{child_idx}] parent_off={child['parent_off']} ptr={child['ptr']} "
                f"head={child['head_text'] or '-'} score={child['score']}"
            )
            if child.get("inline_strings"):
                joined = ", ".join(f"{x['text']}@{x['off']}" for x in child["inline_strings"][:6])
                lines.append(f"        inline_strings: {joined}")
            if child.get("slot_like_records"):
                joined = ", ".join(
                    f"{x['text']}@{x['off']} tag={x['tag_u32']} f=({x['f0']},{x['f1']})"
                    for x in child["slot_like_records"][:6]
                )
                lines.append(f"        slot_records: {joined}")
            if child.get("named_stride_records"):
                joined = ", ".join(
                    f"{x['text']}@{x['off']} mid={x['mid_ptr']} tail={x['tail_u32']}"
                    for x in child["named_stride_records"][:6]
                )
                lines.append(f"        named_records: {joined}")
            if child.get("ptr_code_entries"):
                for rec_idx, rec in enumerate(child["ptr_code_entries"][:8]):
                    summary = rec.get("summary") or {}
                    label = summary.get("head_text") or (
                        summary.get("inline_strings", [{}])[0].get("text") if summary.get("inline_strings") else ""
                    ) or "-"
                    lines.append(
                        f"        ptr_entry[{rec_idx}] off={rec['off']} ptr={rec['ptr']} "
                        f"code=({rec['code_a']},{rec['code_b']}) label={label}"
                    )
            if child.get("float_rows"):
                for row in child["float_rows"][:4]:
                    joined = ", ".join(f"{v:g}" for v in row["values"])
                    lines.append(f"        float_row[{row['off']}]: {joined}")
            if child.get("int_candidates"):
                joined = ", ".join(f"{x['u32']}@{x['off']}" for x in child["int_candidates"][:6])
                lines.append(f"        ints: {joined}")
            if child.get("float_candidates"):
                joined = ", ".join(f"{x['f32']}@{x['off']}" for x in child["float_candidates"][:6])
                lines.append(f"        floats: {joined}")
    return "\n".join(lines).rstrip() + "\n"


def main():
    print("\n" + "=" * 55)
    print("🚀 [SYSTEM BOOT] กำลังสแกนหา Air Secondary Weapon / Bombs...")
    print("=" * 55)

    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    if not pid or not base_addr:
        raise RuntimeError("game process/base not found")

    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    unit_ptr, active_weapon_ptr, weapon_source, scan_notes = try_get_active_weapon(scanner, base_addr)
    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    profile = mul.get_unit_filter_profile(scanner, unit_ptr) or {}
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}

    payload = {
        "generated_at": datetime.now().isoformat(),
        "pid": pid,
        "base": _hex0(base_addr),
        "unit_ptr": _hex0(unit_ptr),
        "cgame_ptr": _hex0(cgame_ptr),
        "unit_key": str(dna.get("name_key") or profile.get("unit_key") or ""),
        "short_name": str(dna.get("short_name") or profile.get("short_name") or ""),
        "family": str(dna.get("family") or profile.get("tag") or ""),
        "profile_kind": str(profile.get("kind") or ""),
        "active_weapon_ptr": _hex0(active_weapon_ptr),
        "active_weapon_source": weapon_source,
        "scan_notes": scan_notes,
    }
    payload["active_profile"] = _read_weapon_profile(scanner, active_weapon_ptr)
    payload["secondary_candidates"] = _scan_secondary_weapon_candidates(scanner, unit_ptr, cgame_ptr, active_weapon_ptr)
    payload["loadout_anchors"] = _scan_loadout_anchors(scanner, unit_ptr)

    os.makedirs(os.path.join(PROJECT_ROOT, "dumps"), exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(PROJECT_ROOT, "dumps", f"air_secondary_weapon_dump_{stamp}.json")
    txt_path = os.path.join(PROJECT_ROOT, "dumps", f"air_secondary_weapon_dump_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(render_text(payload))

    print("\n" + "=" * 58)
    print(" AIR SECONDARY WEAPON / BOMB DUMPER")
    print("=" * 58)
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")


if __name__ == "__main__":
    main()
