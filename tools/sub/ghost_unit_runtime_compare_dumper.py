#!/usr/bin/env python3
import json
import os
import struct
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.utils.scanner import MemoryScanner, get_game_base_address, get_game_pid, init_dynamic_offsets
from src.utils.mul import (
    OFF_GROUND_MOVEMENT,
    OFF_UNIT_INFO,
    OFF_UNIT_STATE,
    get_air_velocity,
    get_all_units,
    get_ground_velocity,
    get_unit_bbox,
    get_unit_detailed_dna,
    get_unit_pos,
    get_unit_status,
    get_unit_filter_profile,
    is_valid_ptr,
)


def _read_ptr(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def _safe_round3(v):
    try:
        return round(float(v), 3)
    except Exception:
        return 0.0


def _vec3(v):
    if not v or len(v) < 3:
        return [0.0, 0.0, 0.0]
    return [_safe_round3(v[0]), _safe_round3(v[1]), _safe_round3(v[2])]


def _bbox_size(scanner, u_ptr):
    try:
        bbox = get_unit_bbox(scanner, u_ptr)
        if not bbox:
            return [0.0, 0.0, 0.0]
        bmin, bmax = bbox
        return [
            _safe_round3((bmax[0] - bmin[0])),
            _safe_round3((bmax[1] - bmin[1])),
            _safe_round3((bmax[2] - bmin[2])),
        ]
    except Exception:
        return [0.0, 0.0, 0.0]


def build_record(scanner, u_ptr, is_air):
    status = get_unit_status(scanner, u_ptr) or (0, -1, "", -1)
    team, state, unit_name, reload_val = status
    dna = get_unit_detailed_dna(scanner, u_ptr) or {}
    profile = get_unit_filter_profile(scanner, u_ptr) or {}
    pos = get_unit_pos(scanner, u_ptr)
    info_ptr = _read_ptr(scanner, u_ptr + OFF_UNIT_INFO)
    mov_ptr = _read_ptr(scanner, u_ptr + OFF_GROUND_MOVEMENT)
    vel = get_air_velocity(scanner, u_ptr) if is_air else get_ground_velocity(scanner, u_ptr)
    state_raw = scanner.read_mem(u_ptr + OFF_UNIT_STATE, 0x20) or b""

    rec = {
        "ptr": hex(u_ptr),
        "is_air": bool(is_air),
        "team": int(team),
        "state": int(state),
        "reload_val": int(reload_val),
        "unit_name": str(unit_name or ""),
        "short_name": str(dna.get("short_name") or profile.get("short_name") or ""),
        "unit_key": str(dna.get("name_key") or profile.get("unit_key") or ""),
        "family": str(dna.get("family") or profile.get("tag") or ""),
        "class_id": int(dna.get("class_id", -1) or -1),
        "nation_id": int(dna.get("nation_id", -1) or -1),
        "is_invul": bool(dna.get("is_invul")),
        "info_ptr": hex(info_ptr) if info_ptr else "0x0",
        "info_ptr_valid": bool(is_valid_ptr(info_ptr)),
        "mov_ptr": hex(mov_ptr) if mov_ptr else "0x0",
        "mov_ptr_valid": bool(is_valid_ptr(mov_ptr)),
        "pos": _vec3(pos),
        "vel": _vec3(vel),
        "bbox_size": _bbox_size(scanner, u_ptr),
        "state_raw_hex": state_raw.hex(),
        "profile_tag": str(profile.get("tag") or ""),
        "profile_path": str(profile.get("path") or ""),
        "profile_kind": str(profile.get("kind") or ""),
        "ghost_suspect": False,
    }

    # Conservative hint only. Final filtering should use compare evidence, not this flag alone.
    rec["ghost_suspect"] = (
        rec["state"] == 0
        and not rec["is_invul"]
        and rec["team"] != 0
        and rec["info_ptr_valid"]
        and rec["mov_ptr_valid"]
        and rec["reload_val"] in (-1, 0)
    )
    return rec


def render_text(payload):
    lines = []
    lines.append("=" * 50)
    lines.append(" GHOST UNIT RUNTIME COMPARE DUMPER")
    lines.append("=" * 50)
    lines.append(f"[+] Units dumped: {len(payload['units'])}")
    lines.append("")
    for rec in payload["units"]:
        flags = []
        if rec["state"] >= 1:
            flags.append("DEAD")
        if rec["ghost_suspect"]:
            flags.append("GHOST?")
        flag_str = f" [{' '.join(flags)}]" if flags else ""
        lines.append(
            f"- {rec['short_name'] or rec['unit_name'] or rec['unit_key']} "
            f"| ptr={rec['ptr']} | team={rec['team']} state={rec['state']} reload={rec['reload_val']}{flag_str}"
        )
        lines.append(
            f"  key={rec['unit_key']} | family={rec['family']} | air={rec['is_air']} | invul={rec['is_invul']}"
        )
        lines.append(
            f"  info={rec['info_ptr']} valid={rec['info_ptr_valid']} | mov={rec['mov_ptr']} valid={rec['mov_ptr_valid']}"
        )
        lines.append(
            f"  pos={rec['pos']} | vel={rec['vel']} | bbox={rec['bbox_size']}"
        )
        lines.append(
            f"  profile={rec['profile_tag']} | kind={rec['profile_kind']} | path={rec['profile_path']}"
        )
        lines.append(f"  state_raw={rec['state_raw_hex']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    print("\n" + "=" * 55)
    print("🚀 [SYSTEM BOOT] กำลังสแกนหา Offsets ด้วย AI สถิติ...")
    print("=" * 55)

    pid = get_game_pid()
    base = get_game_base_address(pid)
    if not pid or not base:
        raise RuntimeError("game process/base not found")

    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)

    units = []
    for u_ptr, is_air in get_all_units(scanner, base):
        try:
            units.append(build_record(scanner, u_ptr, is_air))
        except Exception:
            continue

    stamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs("dumps", exist_ok=True)
    payload = {
        "pid": pid,
        "base": hex(base),
        "generated_at": stamp,
        "units": units,
    }
    json_path = os.path.join("dumps", f"ghost_unit_runtime_compare_{stamp}.json")
    txt_path = os.path.join("dumps", f"ghost_unit_runtime_compare_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(render_text(payload))

    print("\n" + "=" * 50)
    print(" GHOST UNIT RUNTIME COMPARE DUMPER")
    print("=" * 50)
    print(f"[+] Units dumped: {len(units)}")
    print(f"[+] JSON: {os.path.abspath(json_path)}")
    print(f"[+] TEXT: {os.path.abspath(txt_path)}")


if __name__ == "__main__":
    main()
