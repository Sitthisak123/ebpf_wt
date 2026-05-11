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
from tools.sub.my_unit_bomb_reflection_probe import _hex0


PRESET_OFF = 0x7C0
WATCH_START = 0x9F0
WATCH_END = 0xB80
WATCH_STRIDE = 4
PRESET_WATCH_START = 0x10
PRESET_WATCH_END = 0x240
PRESET_WATCH_STRIDE = 4
WARMUP_SEC = 1.0
RUN_SEC = 20.0

FOCUS_OFFSETS = {
    0x7C0: "preset_anchor",
    0xA10: "supportPlanesCount",
    0xA38: "supportPlaneCatapultsFuseMask",
    0xA98: "visualReloadProgress",
    0xAD8: "near_bombDelay_has_payload",
    0xAE8: "bombDelayExplosion",
    0xB00: "near_bombDelay_scalar_a",
    0xB10: "delayWithFlightTime",
    0xB38: "rocketFuseDist",
    0xB60: "torpedoDiveDepth",
    0xB78: "near_torpedo_scalar_a",
}


def _read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return None
    return struct.unpack("<I", raw)[0]


def _read_f32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return None
    return struct.unpack("<f", raw)[0]


def _read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def _snapshot_region(scanner, base_ptr, start_off, end_off, stride):
    out = {}
    if not base_ptr:
        return out
    for off in range(start_off, end_off, stride):
        u32 = _read_u32(scanner, base_ptr + off)
        f32 = _read_f32(scanner, base_ptr + off)
        if u32 is None:
            continue
        out[off] = {"u32": int(u32), "f32": float(f32) if f32 is not None else None}
    return out


def _snapshot(scanner, unit_ptr):
    preset_ptr = _read_u64(scanner, unit_ptr + PRESET_OFF)
    out = {
        "preset_ptr": preset_ptr,
        "my_unit": {},
        "preset_obj": {},
    }
    for off in range(WATCH_START, WATCH_END, WATCH_STRIDE):
        u32 = _read_u32(scanner, unit_ptr + off)
        f32 = _read_f32(scanner, unit_ptr + off)
        if u32 is None:
            continue
        out["my_unit"][off] = {"u32": int(u32), "f32": float(f32) if f32 is not None else None}
    if preset_ptr and mul.is_valid_ptr(preset_ptr):
        out["preset_obj"] = _snapshot_region(scanner, preset_ptr, PRESET_WATCH_START, PRESET_WATCH_END, PRESET_WATCH_STRIDE)
    return out


def _is_interesting_preset_change(off, before_u32, after_u32):
    if before_u32 == after_u32:
        return False
    if 0 <= before_u32 <= 16 or 0 <= after_u32 <= 16:
        return True
    if abs(after_u32 - before_u32) <= 8:
        return True
    if off in (
        0x18, 0x1c, 0x20, 0x24, 0x28, 0x2c, 0x30, 0x34,
        0x74, 0x84, 0xa4, 0xac, 0xb4, 0xbc,
        0xd4, 0xe4, 0xf4, 0x104, 0x114, 0x124, 0x134,
        0x144, 0x154, 0x164, 0x174, 0x184, 0x194, 0x1a4,
        0x1b4, 0x1c4, 0x1d4, 0x1e4, 0x1f4, 0x204, 0x214, 0x224, 0x234,
    ):
        return True
    return False


def _diff_map(prev_map, curr_map, label_map=None, source="my_unit"):
    changes = []
    for off, now in curr_map.items():
        before = prev_map.get(off)
        if not before:
            continue
        if before["u32"] != now["u32"]:
            if source == "preset_obj" and not _is_interesting_preset_change(off, before["u32"], now["u32"]):
                continue
            changes.append({
                "source": source,
                "off": _hex0(off),
                "label": (label_map or {}).get(off, ""),
                "u32_before": before["u32"],
                "u32_after": now["u32"],
                "f32_before": round(before["f32"], 6) if before["f32"] is not None else None,
                "f32_after": round(now["f32"], 6) if now["f32"] is not None else None,
            })
    return changes


def render_text(payload):
    lines = []
    lines.append("=" * 58)
    lines.append(" MY UNIT BOMB REFLECTION WATCH")
    lines.append("=" * 58)
    lines.append(f"PID={payload['pid']} base={payload['base']} unit={payload['unit_ptr']}")
    lines.append(f"unit_key={payload['unit_key']} short_name={payload['short_name']} family={payload['family']}")
    lines.append(f"watch_range={payload['watch_range']}")
    lines.append(f"preset_watch_range={payload['preset_watch_range']}")
    lines.append("[focus-offsets]")
    for off, label in sorted(payload.get("focus_offsets", {}).items(), key=lambda x: int(x[0], 16)):
        lines.append(f"  {off}: {label}")
    lines.append("")
    for event in payload.get("changes", []):
        lines.append(f"[change] t={event['t']}s source={event['source']} off={event['off']} label={event['label'] or '-'}")
        lines.append(
            f"  u32: {event['u32_before']} -> {event['u32_after']} | "
            f"f32: {event['f32_before']} -> {event['f32_after']}"
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

    print("\n" + "=" * 58)
    print(" MY UNIT BOMB REFLECTION WATCH")
    print("=" * 58)
    print(f"unit={hex(unit_ptr)} unit_key={dna.get('name_key') or ''} short_name={dna.get('short_name') or ''}")
    print("[*] Watch mode active. ปล่อย bomb หรือสลับ preset แล้วรอ change log.")

    start_t = time.time()
    prev = _snapshot(scanner, unit_ptr)
    events = []
    while time.time() - start_t < RUN_SEC:
        time.sleep(0.15)
        curr = _snapshot(scanner, unit_ptr)
        elapsed = time.time() - start_t
        if elapsed >= WARMUP_SEC:
            changes = []
            changes.extend(_diff_map(prev.get("my_unit", {}), curr.get("my_unit", {}), FOCUS_OFFSETS, "my_unit"))
            if prev.get("preset_ptr") == curr.get("preset_ptr") and curr.get("preset_obj"):
                changes.extend(_diff_map(prev.get("preset_obj", {}), curr.get("preset_obj", {}), {}, "preset_obj"))
            for ch in changes:
                event = dict(ch)
                event["t"] = round(elapsed, 2)
                events.append(event)
                print(f"[change] t={event['t']:.2f}s source={event['source']} off={event['off']} label={event['label'] or '-'}")
                print(
                    f"  u32: {event['u32_before']} -> {event['u32_after']} | "
                    f"f32: {event['f32_before']} -> {event['f32_after']}"
                )
        prev = curr

    payload = {
        "generated_at": datetime.now().isoformat(),
        "pid": pid,
        "base": _hex0(base_addr),
        "unit_ptr": _hex0(unit_ptr),
        "unit_key": str(dna.get("name_key") or ""),
        "short_name": str(dna.get("short_name") or ""),
        "family": str(dna.get("family") or ""),
        "watch_range": {"start": _hex0(WATCH_START), "end": _hex0(WATCH_END), "stride": _hex0(WATCH_STRIDE)},
        "preset_watch_range": {"start": _hex0(PRESET_WATCH_START), "end": _hex0(PRESET_WATCH_END), "stride": _hex0(PRESET_WATCH_STRIDE)},
        "focus_offsets": {_hex0(k): v for k, v in FOCUS_OFFSETS.items()},
        "changes": events,
    }

    os.makedirs(os.path.join(PROJECT_ROOT, "dumps"), exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(PROJECT_ROOT, "dumps", f"my_unit_bomb_reflection_watch_{stamp}.json")
    txt_path = os.path.join(PROJECT_ROOT, "dumps", f"my_unit_bomb_reflection_watch_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(render_text(payload))

    print(f"\n[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")


if __name__ == "__main__":
    main()
