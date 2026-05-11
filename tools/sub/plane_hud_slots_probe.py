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


HUD_PTR_CANDIDATES = (
    0x6CD49E8,  # offsets/ref.txt (older)
    0x6C0FEA8,  # offsets/ref.txt
    0x6CDB9B8,  # src/v1/scanner/_win_ref_offsets
)
CHAIN_ROOT_CANDIDATES = (
    ("cgame", 0x6C108B8),
    ("localplayer", 0x6BEDA30),
    ("hud_ref_a", 0x6CD49E8),
    ("hud_ref_b", 0x6C0FEA8),
    ("hud_ref_c", 0x6CDB9B8),
)
CHAIN_SCAN_WINDOW = 0x1000
CHAIN_SCAN_STRIDE = 0x8
CHAIN_MAX_DEPTH = 2
CHAIN_MAX_NODES = 256

HUD_FIELDS = {
    "planeBombingMode": 0x6390,
    "planeSelectedTrigger": 0x64B0,
    "planeBombCCIPMode": 0x64E0,
    "planeTargetPosValid": 0x6510,
    "planeTargetPos": 0x6540,
    "planeTimeBeforeBombRelease": 0x6570,
    "planeCurWeaponName": 0x66F0,
    "planeCurWeaponGuidanceType": 0x6720,
    "planeLaserAgmCnt": 0x6750,
    "planeLaserAgmSelectedCnt": 0x6780,
    "planeWeaponSlots": 0x6E40,
    "planeWeaponSlotActive": 0x6E70,
    "planeWeaponSlotsTrigger": 0x6EA0,
    "planeWeaponSlotsCnt": 0x6ED0,
    "planeWeaponSlotsTotalCnt": 0x6F00,
    "planeWeaponSlotsName": 0x6F30,
    "planeWeaponSlotsBulletId": 0x6F60,
    "planeWeaponSlotsJettisoned": 0x6F90,
    "planeWeaponSlotsGuidanceType": 0x6FC0,
    "planeSlotCount": 0x6FF0,
}


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


def _read_ptr(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def _read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return 0
    return struct.unpack("<I", raw)[0]


def _read_f32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return None
    return struct.unpack("<f", raw)[0]


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
    if len(text) < 2 or not any(ch.isalnum() for ch in text):
        return None
    return text


def _looks_like_runtime_ptr(ptr_text):
    try:
        ptr = int(str(ptr_text or "0"), 16)
    except Exception:
        return False
    return ptr >= 0x100000


def _is_readable_ptr(scanner, ptr, size=0x20):
    if not mul.is_valid_ptr(ptr):
        return False
    raw = scanner.read_mem(ptr, size)
    return bool(raw and len(raw) >= min(size, 0x10))


def _extract_inline_strings(raw, min_len=3, limit=12):
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


def _iter_pointer_fields(scanner, obj_ptr, window=CHAIN_SCAN_WINDOW, stride=CHAIN_SCAN_STRIDE):
    seen = set()
    for off in range(0, window, stride):
        child_ptr = _read_ptr(scanner, obj_ptr + off)
        if not _looks_like_runtime_ptr(hex(child_ptr)) or child_ptr in seen:
            continue
        if not _is_readable_ptr(scanner, hex(child_ptr), 0x20):
            continue
        seen.add(child_ptr)
        yield off, child_ptr


def _score_hud_root(scanner, ptr):
    if not _is_readable_ptr(scanner, ptr, 0x100):
        return -1, {}
    max_off = max(HUD_FIELDS.values())
    hits = []
    score = 0
    nonzero_fields = 0
    readable_ptr_fields = 0
    semantic_text_fields = 0
    for name, off in HUD_FIELDS.items():
        if off > max_off:
            continue
        field_ptr = _read_ptr(scanner, ptr + off)
        u32 = _read_u32(scanner, ptr + off)
        f32 = _read_f32(scanner, ptr + off)
        text = ""
        ptr_readable = _is_readable_ptr(scanner, field_ptr, 0x40)
        if ptr_readable:
            readable_ptr_fields += 1
            text = _read_inline_ascii(scanner, field_ptr, 96) or mul._read_c_string(scanner, field_ptr, 96) or ""
        blob = f"{name} {text}".lower()
        field_score = 0
        if ptr_readable:
            field_score += 4
            if text:
                field_score += 4
                semantic_text_fields += 1
        if ptr_readable and any(k in blob for k in ("bomb", "weapon", "slot", "trigger", "ccip", "target", "guidance", "release")):
            field_score += 10
        if name in ("planeBombingMode", "planeSelectedTrigger", "planeBombCCIPMode", "planeWeaponSlotActive", "planeSlotCount"):
            if 0 <= u32 <= 64:
                field_score += 2
        if name in ("planeWeaponSlotsCnt", "planeWeaponSlotsTotalCnt", "planeWeaponSlotsBulletId", "planeWeaponSlotsGuidanceType", "planeWeaponSlotsJettisoned"):
            if 0 <= u32 <= 4096:
                field_score += 2
        if name == "planeTimeBeforeBombRelease" and f32 is not None and -1.0 <= f32 <= 60.0:
            field_score += 6
        if name in ("planeBombingMode", "planeSelectedTrigger", "planeBombCCIPMode", "planeWeaponSlotActive") and u32 == 0:
            field_score += 1
        if name in ("planeWeaponSlotsCnt", "planeWeaponSlotsTotalCnt", "planeSlotCount") and 0 <= u32 <= 32:
            field_score += 4
        if name == "planeTargetPos":
            xs = [_read_f32(scanner, ptr + off + k) for k in (0, 4, 8)]
            if all(v is not None and -100000.0 <= v <= 100000.0 for v in xs):
                if any(abs(v) > 0.0001 for v in xs):
                    field_score += 4
                else:
                    field_score += 1
                if any(abs(v) > 0.0001 for v in xs):
                    nonzero_fields += 1
        if name in ("planeBombingMode", "planeSelectedTrigger", "planeBombCCIPMode", "planeTargetPosValid", "planeWeaponSlotActive") and 0 <= u32 <= 64:
            nonzero_fields += 1
        elif name in ("planeWeaponSlotsCnt", "planeWeaponSlotsTotalCnt", "planeSlotCount") and 0 <= u32 <= 256:
            nonzero_fields += 1
        elif name == "planeTimeBeforeBombRelease" and f32 is not None and -1.0 <= f32 <= 60.0:
            nonzero_fields += 1
        elif u32 != 0:
            nonzero_fields += 1
        elif f32 is not None and abs(f32) > 0.0001:
            nonzero_fields += 1
        if field_score > 0:
            hits.append({
                "field": name,
                "off": _hex0(off),
                "ptr": _hex0(field_ptr),
                "text": text,
                "u32": int(u32),
                "f32": _safe_round(f32) if f32 is not None else None,
                "score": field_score,
            })
            score += field_score
    if nonzero_fields == 0 and readable_ptr_fields == 0 and semantic_text_fields == 0:
        score -= 500
    elif nonzero_fields <= 2 and readable_ptr_fields == 0:
        score -= 200
    if readable_ptr_fields == 0 and semantic_text_fields == 0 and score > 40:
        score -= 300
    meta = {
        "ptr": _hex0(ptr),
        "field_ptr_hits": sorted(hits, key=lambda x: (-x["score"], x["off"]))[:32],
        "nonzero_fields": nonzero_fields,
        "readable_ptr_fields": readable_ptr_fields,
        "semantic_text_fields": semantic_text_fields,
    }
    return score, meta


def _resolve_hud_root(scanner, base_addr):
    best = None
    queue = []
    seen_nodes = set()
    for label, off in CHAIN_ROOT_CANDIDATES:
        ptr = _read_ptr(scanner, base_addr + off)
        if not _looks_like_runtime_ptr(hex(ptr)) or not _is_readable_ptr(scanner, hex(ptr), 0x20):
            continue
        queue.append((label, _hex0(off), ptr, 0, []))

    explored = 0
    while queue and explored < CHAIN_MAX_NODES:
        seed_label, seed_off, ptr, depth, path = queue.pop(0)
        if ptr in seen_nodes:
            continue
        seen_nodes.add(ptr)
        explored += 1
        score, meta = _score_hud_root(scanner, ptr)
        candidate = {
            "seed": seed_label,
            "seed_off": seed_off,
            "hud_ptr": _hex0(ptr),
            "score": score,
            "depth": depth,
            "path": path,
            "meta": meta,
        }
        if best is None or score > best["score"]:
            best = candidate
        if depth >= CHAIN_MAX_DEPTH:
            continue
        for child_off, child_ptr in _iter_pointer_fields(scanner, ptr):
            child_path = path + [{
                "from": _hex0(ptr),
                "field_off": _hex0(child_off),
                "to": _hex0(child_ptr),
            }]
            queue.append((seed_label, seed_off, child_ptr, depth + 1, child_path))
    return best or {}


def _summarize_field(scanner, hud_ptr, off, size=0x180):
    ptr = _read_ptr(scanner, hud_ptr + off)
    u32 = _read_u32(scanner, hud_ptr + off)
    f32 = _read_f32(scanner, hud_ptr + off)
    item = {
        "off": _hex0(off),
        "raw_ptr": _hex0(ptr),
        "u32": int(u32),
        "f32": _safe_round(f32) if f32 is not None else None,
    }
    target_ptr = ptr if mul.is_valid_ptr(ptr) else 0
    if target_ptr:
        raw = scanner.read_mem(target_ptr, size) or b""
        item["head_text"] = _read_inline_ascii(scanner, target_ptr, 96) or mul._read_c_string(scanner, target_ptr, 96) or ""
        item["inline_strings"] = _extract_inline_strings(raw, min_len=3, limit=16)
        ints = []
        floats = []
        for sub_off in range(0, min(size, len(raw)), 4):
            vv = _read_u32(scanner, target_ptr + sub_off)
            if vv in (0, 1, 2, 3, 4, 5, 6, 8, 9, 13, 79, 97, 114, 201, 250, 500):
                ints.append({"off": _hex0(sub_off), "u32": int(vv)})
            ff = _read_f32(scanner, target_ptr + sub_off)
            if ff is not None and any(abs(ff - r) <= 1.0 for r in (1.0, 2.0, 4.0, 6.0, 13.0, 79.0, 97.0, 114.0, 250.0, 500.0)):
                floats.append({"off": _hex0(sub_off), "f32": _safe_round(ff)})
        item["int_hits"] = ints[:24]
        item["float_hits"] = floats[:24]
    return item


def render_text(payload):
    lines = []
    lines.append("=" * 58)
    lines.append(" PLANE HUD SLOTS PROBE")
    lines.append("=" * 58)
    lines.append(f"PID={payload['pid']} base={payload['base']} unit={payload['unit_ptr']}")
    lines.append(f"unit_key={payload['unit_key']} short_name={payload['short_name']} family={payload['family']}")
    hud = payload.get("hud_root") or {}
    lines.append(
        f"hud_seed={hud.get('seed','')} seed_off={hud.get('seed_off','0x0')} "
        f"hud_ptr={hud.get('hud_ptr','0x0')} score={hud.get('score',-1)} depth={hud.get('depth',-1)}"
    )
    if hud.get("path"):
        lines.append("[hud-path]")
        for step in hud["path"][:8]:
            lines.append(f"  {step['from']} + {step['field_off']} -> {step['to']}")
    lines.append("")
    lines.append("[hud-field-ptr-hits]")
    for item in (hud.get("meta") or {}).get("field_ptr_hits", []):
        lines.append(f"  {item['field']} off={item['off']} ptr={item['ptr']} text={item.get('text','')}")
    lines.append("")
    lines.append("[field-summaries]")
    for name, item in payload.get("fields", {}).items():
        lines.append(f"  {name} off={item['off']} raw_ptr={item['raw_ptr']} u32={item['u32']} f32={item['f32']}")
        if item.get("head_text"):
            lines.append(f"      head_text: {item['head_text']}")
        if item.get("inline_strings"):
            joined = ", ".join(f"{x['text']}@{x['off']}" for x in item['inline_strings'][:8])
            lines.append(f"      inline_strings: {joined}")
        if item.get("int_hits"):
            joined = ", ".join(f"{x['u32']}@{x['off']}" for x in item['int_hits'][:12])
            lines.append(f"      int_hits: {joined}")
        if item.get("float_hits"):
            joined = ", ".join(f"{x['f32']}@{x['off']}" for x in item['float_hits'][:12])
            lines.append(f"      float_hits: {joined}")
    return "\n".join(lines).rstrip() + "\n"


def main():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    if not pid or not base_addr:
        raise RuntimeError("game process/base not found")

    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)
    unit_ptr, _my_team = mul.get_local_team(scanner, base_addr)
    unit_ptr = unit_ptr or 0
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}

    hud = _resolve_hud_root(scanner, base_addr)
    hud_ptr = int(hud.get("hud_ptr", "0x0"), 16) if hud else 0

    fields = {}
    if mul.is_valid_ptr(hud_ptr):
        for name, off in HUD_FIELDS.items():
            fields[name] = _summarize_field(scanner, hud_ptr, off)

    payload = {
        "generated_at": datetime.now().isoformat(),
        "pid": pid,
        "base": _hex0(base_addr),
        "unit_ptr": _hex0(unit_ptr),
        "unit_key": str(dna.get("name_key") or ""),
        "short_name": str(dna.get("short_name") or ""),
        "family": str(dna.get("family") or ""),
        "hud_root": hud,
        "fields": fields,
    }

    os.makedirs(os.path.join(PROJECT_ROOT, "dumps"), exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(PROJECT_ROOT, "dumps", f"plane_hud_slots_probe_{stamp}.json")
    txt_path = os.path.join(PROJECT_ROOT, "dumps", f"plane_hud_slots_probe_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(render_text(payload))

    print("\n" + "=" * 58)
    print(" PLANE HUD SLOTS PROBE")
    print("=" * 58)
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")


if __name__ == "__main__":
    main()
