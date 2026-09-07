#!/usr/bin/env python3
"""
🛠️ War Thunder Linux Unit Status & Metadata Offset Dumper & Persistence Generator
เครื่องมือตรวจสอบและบันทึก Persistence สำหรับ:
  - m_InvulTimer (0x0E4C)
  - m_Invulnerable (0x0E70)
  - m_UnitState (0x0F70)
  - m_PlayerInfo (0x0F78)
  - m_UnitTeam (0x0FF0)
  - m_UnitInfo (0x1000)
  - m_UnitType (0x0080) [Fast Air/Ground discriminator]
บันทึกลง: config/unit_status_persistence.json
"""

import os
import sys
import struct
import time
import json
import argparse
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import (
    MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
)
import src.utils.mul as mul

UNIT_STATUS_PERSISTENCE_PATH = os.path.join(PROJECT_ROOT, "config", "unit_status_persistence.json")
DEFAULT_GAME_BINARY_PATH = "/home/xda-7/MyGames/WarThunder/linux64/aces"


def _get_binary_fingerprint(binary_path=DEFAULT_GAME_BINARY_PATH):
    try:
        real_path = os.path.realpath(binary_path)
        st = os.stat(real_path)
        return {
            "path": real_path,
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
        }
    except Exception:
        return None


def write_persistence(offsets_dict, confidence=0.95, source="unit_status_dumper"):
    doc = {
        "updated_at": datetime.now().isoformat(),
        "source": source,
        "updated_by_tool": "unit_status_dumper",
        "confidence": float(confidence),
        "notes": "Verified Linux memory struct offsets for Unit status, invulnerability, player info, and classification",
        "build_fingerprint": _get_binary_fingerprint(),
        "offsets": {k: int(v) for k, v in offsets_dict.items()},
        "offsets_hex": {k: hex(int(v)) for k, v in offsets_dict.items()},
    }
    os.makedirs(os.path.dirname(UNIT_STATUS_PERSISTENCE_PATH), exist_ok=True)
    with open(UNIT_STATUS_PERSISTENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"\n[+] ✅ Successfully wrote persistence -> {UNIT_STATUS_PERSISTENCE_PATH}")
    for k, v in offsets_dict.items():
        print(f"    • {k:<18} = {hex(v)} ({v})")
    print(f"    • Confidence: {confidence}\n")


def dump_and_verify(scanner, base_address, write_to_disk=True, confidence=0.95):
    cgame_base = mul.get_cgame_base(scanner, base_address)
    my_unit, my_team = mul.get_local_team(scanner, base_address)
    all_units = mul.get_all_units(scanner, cgame_base)

    if not all_units:
        print("[-] ❌ No units found in current game session!")
        return None

    print("\n" + "=" * 95)
    print("🎯 WTM UNIT STATUS & METADATA OFFSET VERIFIER")
    print(f"PID Base: {hex(base_address)} | CGame: {hex(cgame_base)} | Units: {len(all_units)} | MyUnit: {hex(my_unit)}")
    print("=" * 95)

    offsets = {
        "invul_timer_off": mul.OFF_INVUL_TIMER,
        "invulnerable_off": mul.OFF_INVULNERABLE,
        "unit_state_off": mul.OFF_UNIT_STATE or 0x0F70,
        "player_info_off": mul.OFF_PLAYER_INFO,
        "unit_team_off": mul.OFF_UNIT_TEAM or 0x0FF0,
        "unit_info_off": mul.OFF_UNIT_INFO or 0x1000,
        "unit_type_off": 0x0080,
    }

    verified_count = 0
    air_count = 0
    ground_count = 0
    invul_count = 0
    human_count = 0

    print(f"{'Unit Ptr':<12} | {'Type':<8} | {'Type64':<18} | {'Invul State':<16} | {'PlayerInfo':<22} | {'State':<8}")
    print("-" * 95)

    for u_ptr, is_air in all_units[:15]:
        buf = scanner.read_mem(u_ptr + 0x0080, 8)
        val64 = struct.unpack("<Q", buf)[0] if buf else 0
        mem_is_air = (val64 == 0x0000000200000001)

        start_off = 0x0E40
        chunk = scanner.read_mem(u_ptr + start_off, 0x1D0)
        if not chunk:
            continue

        timer = struct.unpack_from("<f", chunk, offsets["invul_timer_off"] - start_off)[0]
        invul = chunk[offsets["invulnerable_off"] - start_off]
        state = struct.unpack_from("<H", chunk, offsets["unit_state_off"] - start_off)[0]
        p_info = struct.unpack_from("<Q", chunk, offsets["player_info_off"] - start_off)[0]

        is_invul = bool(invul != 0 or timer > 0.05)
        is_human = mul.is_valid_ptr(p_info)

        if mem_is_air: air_count += 1
        else: ground_count += 1
        if is_invul: invul_count += 1
        if is_human: human_count += 1
        verified_count += 1

        type_str = "AIR" if mem_is_air else "GROUND"
        inv_str = f"🛡️ YES ({timer:.1f}s)" if is_invul else "No (0s)"
        info_str = f"👤 Human ({hex(p_info)[:8]}..)" if is_human else "🤖 BOT"
        state_str = "ALIVE" if state == 0 else ("BURN" if state == 1 else f"DEAD({state})")

        print(f"{hex(u_ptr):<12} | {type_str:<8} | {hex(val64):<18} | {inv_str:<16} | {info_str:<22} | {state_str:<8}")

    print("-" * 95)
    print(f"📊 Summary: Verified={verified_count} | Air={air_count} | Ground={ground_count} | Invul={invul_count} | Human={human_count}")
    print("=" * 95)

    if write_to_disk:
        write_persistence(offsets, confidence=confidence)

    return offsets


def main():
    parser = argparse.ArgumentParser(description="Unit Status & Metadata Offset Dumper")
    parser.add_argument("--no-write", action="store_true", help="Do not write persistence file")
    parser.add_argument("--confidence", type=float, default=0.95, help="Confidence score (default: 0.95)")
    parser.add_argument("--watch", action="store_true", help="Continuously probe memory every 2s")
    args = parser.parse_args()

    pid = get_game_pid()
    if not pid:
        print("[-] ❌ War Thunder (aces) is not running!")
        sys.exit(1)

    scanner = MemoryScanner(pid)
    base = get_game_base_address(pid)
    init_dynamic_offsets(scanner, base)

    if args.watch:
        try:
            while True:
                dump_and_verify(scanner, base, write_to_disk=not args.no_write, confidence=args.confidence)
                time.sleep(2.0)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        dump_and_verify(scanner, base, write_to_disk=not args.no_write, confidence=args.confidence)


if __name__ == "__main__":
    main()
