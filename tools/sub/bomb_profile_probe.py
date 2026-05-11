#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_base_address, get_game_pid, init_dynamic_offsets
import src.utils.mul as mul
from src.utils.bomb_profile import normalize_bomb_profile_table, resolve_runtime_bomb_profile


BOMB_PROFILE_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "bomb_profile_table.json")


def _hex0(v):
    try:
        return hex(int(v or 0))
    except Exception:
        return "0x0"


def _read_inline_ascii(scanner, ptr, size=128):
    if not mul.is_valid_ptr(ptr):
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


def _read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    import struct
    return struct.unpack("<Q", raw)[0]


def _load_table():
    if not os.path.exists(BOMB_PROFILE_CONFIG_PATH):
        return {}
    with open(BOMB_PROFILE_CONFIG_PATH, "r", encoding="utf-8") as f:
        doc = json.load(f)
    return normalize_bomb_profile_table(doc)


def render_text(payload):
    lines = []
    lines.append("=" * 58)
    lines.append(" BOMB PROFILE PROBE")
    lines.append("=" * 58)
    lines.append(f"PID={payload['pid']} base={payload['base']} unit={payload['unit_ptr']}")
    lines.append(f"unit_key={payload['unit_key']} short_name={payload['short_name']} family={payload['family']}")
    lines.append(f"preset_ptr={payload['preset_ptr']} preset_name={payload['preset_name']}")
    lines.append(f"matched={payload['matched']} match_source={payload.get('match_source','')}")
    profile = payload.get("profile") or {}
    if profile:
        lines.append("[profile]")
        for key in (
            "display_name",
            "initial_count",
            "bomb_mass",
            "explosive_mass",
            "armor_pen",
            "explode_radius",
            "fragment_radius",
            "drag_profile",
            "notes",
        ):
            lines.append(f"  {key}={profile.get(key)}")
    return "\n".join(lines).rstrip() + "\n"


def main():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    if not pid or not base_addr:
        raise RuntimeError("game process/base not found")
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)
    unit_ptr, _team = mul.get_local_team(scanner, base_addr)
    if not unit_ptr:
        raise RuntimeError("local unit not found")
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    table = _load_table()
    resolved = resolve_runtime_bomb_profile(scanner, unit_ptr, table, _read_u64, _read_inline_ascii, mul._read_c_string)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "pid": pid,
        "base": _hex0(base_addr),
        "unit_ptr": _hex0(unit_ptr),
        "unit_key": str(dna.get("name_key") or ""),
        "short_name": str(dna.get("short_name") or ""),
        "family": str(dna.get("family") or ""),
        "preset_ptr": _hex0(resolved.get("preset_ptr", 0)),
        "preset_name": resolved.get("preset_name", ""),
        "matched": bool(resolved.get("matched")),
        "match_source": str(resolved.get("match_source", "") or ""),
        "profile": resolved.get("profile", {}),
    }
    os.makedirs(os.path.join(PROJECT_ROOT, "dumps"), exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(PROJECT_ROOT, "dumps", f"bomb_profile_probe_{stamp}.json")
    txt_path = os.path.join(PROJECT_ROOT, "dumps", f"bomb_profile_probe_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(render_text(payload))
    print("\n" + "=" * 58)
    print(" BOMB PROFILE PROBE")
    print("=" * 58)
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")


if __name__ == "__main__":
    main()
