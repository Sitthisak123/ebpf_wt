#!/usr/bin/env python3
"""
🛠️ War Thunder Linux Memory Struct Probe & Dumper
เครื่องมือตรวจสอบและทดสอบ Offset สำคัญบน Linux สำหรับ:
  1. m_Invulnerable (0xE70) & m_InvulTimer (0xE4C)
  2. m_PlayerInfo (0xF78) [แยกระหว่าง Human Player vs AI Bot]
  3. m_UnitState (0xF70)
  4. m_UnitType (0x80 / 0x84)
  5. Ballistics & Caliber (0x3F0 -> 0x20F0)
"""

import os
import sys
import time
import math
import struct

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import (
    MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
)
from src.utils.mul import (
    get_cgame_base, get_all_units, get_local_team, get_unit_pos,
    get_unit_status, is_valid_ptr, OFF_WEAPON_PTR, OFF_BULLET_SPEED,
    OFF_BULLET_MASS, OFF_BULLET_CALIBER
)

# Linux Offsets (Derived from Windows reference shifted by -0x10)
OFF_LINUX_INVUL_TIMER = 0x0E4C  # float: Spawn protection remaining time in seconds
OFF_LINUX_INVULNERABLE = 0x0E70  # uint8: 1 if invulnerable, 0 otherwise
OFF_LINUX_PLAYER_INFO = 0x0F78   # uint64: Pointer to Player struct (None/0 for bots)
OFF_LINUX_UNIT_STATE = 0x0F70    # uint16: 0=normal, 1=critical/burning, >=2=dead
OFF_LINUX_ARMORY = 0x10A8        # uint64: Pointer to weapon/armory container


def probe_units():
    pid = get_game_pid()
    if not pid:
        print("❌ War Thunder (aces) is not running!")
        return

    scanner = MemoryScanner(pid)
    base_addr = get_game_base_address(pid)
    init_dynamic_offsets(scanner, base_addr)
    cgame_base = get_cgame_base(scanner, base_addr)
    my_unit, my_team = get_local_team(scanner, base_addr)

    print("\n" + "=" * 95)
    print("🎯 WTM PROBE DUMPER: VERIFYING LINUX OFFSETS ON LIVE GAME")
    print(f"PID: {pid} | Base: {hex(base_addr)} | CGame: {hex(cgame_base)} | MyUnit: {hex(my_unit)}")
    print("=" * 95)

    all_units = get_all_units(scanner, cgame_base)
    print(f"📡 Found {len(all_units)} units in current match:\n")

    header = (
        f"{'Unit Ptr':<12} | {'Role/Type':<10} | {'Invul State':<18} | "
        f"{'PlayerInfo (Bot/Real)':<24} | {'State':<8} | {'Pos (X, Z)':<18}"
    )
    print(header)
    print("-" * 95)

    for u in all_units:
        u_ptr = u[0]
        raw_mem = scanner.read_mem(u_ptr, 0x1100)
        if not raw_mem:
            continue

        is_my = (u_ptr == my_unit)
        is_air = (u[1] == 'air')
        type_str = "MY_UNIT" if is_my else ("AIR" if is_air else "GROUND")

        # 1. Invulnerable & Timer
        invul_timer = struct.unpack_from('<f', raw_mem, OFF_LINUX_INVUL_TIMER)[0]
        invul_bool = raw_mem[OFF_LINUX_INVULNERABLE]
        if invul_bool or invul_timer > 0.05:
            invul_str = f"🛡️ YES ({invul_timer:.1f}s)"
        else:
            invul_str = "No (0s)"

        # 2. PlayerInfo & Bot Check
        p_info = struct.unpack_from('<Q', raw_mem, OFF_LINUX_PLAYER_INFO)[0]
        is_human = is_valid_ptr(p_info)
        p_info_str = f"👤 Human ({hex(p_info)[:8]}..)" if is_human else "🤖 BOT / AI"

        # 3. Unit State (0=Alive, 1=Crit, >=2=Dead)
        unit_state = struct.unpack_from('<H', raw_mem, OFF_LINUX_UNIT_STATE)[0]
        if unit_state == 0:
            state_str = "ALIVE"
        elif unit_state == 1:
            state_str = "BURNING"
        else:
            state_str = f"DEAD({unit_state})"

        # 4. Position
        pos = get_unit_pos(scanner, u_ptr)
        pos_str = f"({pos[0]:.1f}, {pos[2]:.1f})" if pos else "(N/A)"

        print(
            f"{hex(u_ptr):<12} | {type_str:<10} | {invul_str:<18} | "
            f"{p_info_str:<24} | {state_str:<8} | {pos_str:<18}"
        )

    # 5. Weapon Ballistics Probing
    print("\n" + "=" * 95)
    print("🔫 PROBING BALLISTICS & DYNAMIC CALIBER FROM WEAPON STRUCT:")
    print("=" * 95)
    if cgame_base:
        raw_w = scanner.read_mem(cgame_base + OFF_WEAPON_PTR, 8)
        if raw_w:
            w_ptr = struct.unpack("<Q", raw_w)[0]
            print(f"[*] Weapon Ptr (CGame + {hex(OFF_WEAPON_PTR)}): {hex(w_ptr)} (Valid: {is_valid_ptr(w_ptr)})")
            if is_valid_ptr(w_ptr):
                b_speed_data = scanner.read_mem(w_ptr + 0x20E8, 4)
                b_mass_data = scanner.read_mem(w_ptr + 0x20F4, 4)
                b_cal_data = scanner.read_mem(w_ptr + 0x20F8, 4)

                speed = struct.unpack("<f", b_speed_data)[0] if b_speed_data else 0.0
                mass = struct.unpack("<f", b_mass_data)[0] if b_mass_data else 0.0
                cal_m = struct.unpack("<f", b_cal_data)[0] if b_cal_data else 0.0
                cal_mm = cal_m * 1000.0

                print(f"  • Bullet Muzzle Velocity: {speed:.1f} m/s")
                print(f"  • Bullet Mass:           {mass:.3f} kg")
                print(f"  • Bullet Caliber (Raw):   {cal_m:.4f} m ({cal_mm:.1f} mm)")

                if 5.0 <= cal_mm <= 500.0:
                    print(f"  [+] ✅ BINGO! Dynamic Caliber Identified: {cal_mm:.1f} mm")
                else:
                    print("  [!] Caliber out of typical bounds.")
    print("=" * 95 + "\n")


if __name__ == "__main__":
    probe_units()
