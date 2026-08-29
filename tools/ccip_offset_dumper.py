#!/usr/bin/env python3
"""
CCIP & Ballistics Container Offset Test Dumper Tool

Tests & verifies:
1. cGame Base, My Unit Pointer, & Weapon Container Pointer (OFF_WEAPON_PTR / 0x3F0)
2. Ballistics Data (Muzzle Velocity, Bullet Mass, Caliber, CD / Cx)
3. Direct CCIP Impact Pointer & Vector 3D (OFF_CCIP_IMPACT / 0x1C9C)
4. Candidate offsets scan around weapon container and impact points

Usage:
  sudo .venv/bin/python3 tools/ccip_offset_dumper.py
"""

import os
import sys
import time
import struct
import math

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

OFF_CCIP_IMPACT = 0x1C9C  # vec3_t (x, y, z) impact point calculated by Dagor engine

def print_header(title):
    print("\n" + "=" * 70)
    print(f" 🎯 {title}")
    print("=" * 70)

def dump_ccip_offsets():
    pid = get_game_pid()
    if not pid:
        print("❌ War Thunder process (aces) not found!")
        print("   Please start War Thunder and join a battle or test flight.")
        return

    print(f"✅ Found Game PID: {pid}")

    base_addr = get_game_base_address(pid)
    if not base_addr:
        print("❌ Could not get game base address.")
        return
    print(f"✅ Game Base Address: 0x{base_addr:X}")

    # Initialize Scanner and DNA offsets
    try:
        scanner = MemoryScanner(pid)
    except PermissionError:
        print("❌ Permission denied reading /proc/{pid}/mem.")
        print("   Please run with sudo: sudo .venv/bin/python3 tools/ccip_offset_dumper.py")
        return
    except Exception as e:
        print(f"❌ Failed to create MemoryScanner: {e}")
        return

    print("[*] Initializing DNA dynamic offsets...")
    try:
        init_dynamic_offsets(scanner, base_addr)
    except Exception as e:
        print(f"⚠️ Warning during init_dynamic_offsets: {e}")

    cgame_base = mul.get_cgame_base(scanner, base_addr)
    unit_ptr, team_id = mul.get_local_team(scanner, base_addr)
    my_pos = mul.get_unit_pos(scanner, unit_ptr)

    print(f"✅ cGame Base: 0x{cgame_base:X}" if mul.is_valid_ptr(cgame_base) else f"⚠️ cGame Base: 0x{cgame_base:X} (Unverified)")
    print(f"✅ My Unit Ptr: 0x{unit_ptr:X} (Team ID: {team_id})" if mul.is_valid_ptr(unit_ptr) else f"⚠️ My Unit Ptr: 0x{unit_ptr:X}")
    if my_pos:
        print(f"✅ Local Position: X={my_pos[0]:.2f}, Y={my_pos[1]:.2f}, Z={my_pos[2]:.2f}")

    print_header("1. WEAPON & BALLISTIC CONTAINER POINTER DISCOVERY")
    
    weapon_ptr = 0
    weapon_src = "None"
    off_w = getattr(mul, "OFF_WEAPON_PTR", 0x3F0)

    # Check Unit + OFF_WEAPON_PTR
    if mul.is_valid_ptr(unit_ptr):
        raw_w = scanner.read_mem(unit_ptr + off_w, 8)
        if raw_w and len(raw_w) == 8:
            ptr_cand = struct.unpack("<Q", raw_w)[0]
            if mul.is_valid_ptr(ptr_cand):
                weapon_ptr = ptr_cand
                weapon_src = f"unit_ptr + 0x{off_w:X}"

    # Check cgame_base + OFF_WEAPON_PTR
    if not mul.is_valid_ptr(weapon_ptr) and mul.is_valid_ptr(cgame_base):
        raw_w = scanner.read_mem(cgame_base + off_w, 8)
        if raw_w and len(raw_w) == 8:
            ptr_cand = struct.unpack("<Q", raw_w)[0]
            if mul.is_valid_ptr(ptr_cand):
                weapon_ptr = ptr_cand
                weapon_src = f"cgame_base + 0x{off_w:X}"

    # Scan nearby candidate offsets if weapon_ptr is still not found
    if not mul.is_valid_ptr(weapon_ptr):
        print(f"⚠️ Direct read at 0x{off_w:X} did not return valid pointer. Scanning candidate offsets...")
        candidate_offsets = [0x3E0, 0x3E8, 0x3F0, 0x3F8, 0x400, 0x408, 0x480, 0x670, 0xFC0]
        base_targets = []
        if mul.is_valid_ptr(unit_ptr): base_targets.append(("unit_ptr", unit_ptr))
        if mul.is_valid_ptr(cgame_base): base_targets.append(("cgame_base", cgame_base))

        for name, b_ptr in base_targets:
            for cand in candidate_offsets:
                raw = scanner.read_mem(b_ptr + cand, 8)
                if raw and len(raw) == 8:
                    val = struct.unpack("<Q", raw)[0]
                    if mul.is_valid_ptr(val):
                        print(f"  [Found Pointer Candidate] {name} + 0x{cand:04X} -> 0x{val:X}")
                        if weapon_ptr == 0:
                            weapon_ptr = val
                            weapon_src = f"{name} + 0x{cand:X}"

    print(f"\n🎯 Selected Weapon Container Pointer: 0x{weapon_ptr:X} (Source: {weapon_src})")
    
    if not mul.is_valid_ptr(weapon_ptr):
        print("❌ Cannot find valid Weapon/Ballistics Container pointer.")
        print("   Make sure you are spawned in a vehicle (tank/plane) with active weapons.")
        return

    print_header("2. BULLET & BALLISTICS PROPERTIES SCAN")
    known_fields = {
        "Muzzle Speed": getattr(mul, "OFF_BULLET_SPEED", 0x20E0),
        "Bullet Mass": getattr(mul, "OFF_BULLET_MASS", 0x20EC),
        "Caliber (m)": getattr(mul, "OFF_BULLET_CALIBER", 0x20F0),
        "Drag Coeff (Cd)": getattr(mul, "OFF_BULLET_CD", 0x20F4),
    }
    
    for label, off in known_fields.items():
        raw_val = scanner.read_mem(weapon_ptr + off, 4)
        if raw_val and len(raw_val) == 4:
            val = struct.unpack("<f", raw_val)[0]
            print(f"  [{label:<18}] @ 0x{off:04X} = {val:12.6f} | Hex: {raw_val.hex()}")
        else:
            print(f"  [{label:<18}] @ 0x{off:04X} = READ FAILED")

    print_header("3. DIRECT CCIP IMPACT POINT SCAN (+ 0x1C9C / Region)")
    
    print(f"{'Offset':>10} | {'X':>12} | {'Y':>12} | {'Z':>12} | Status / Reason")
    print("-" * 75)

    offsets_to_scan = [0x1C80, 0x1C8C, 0x1C90, 0x1C9C, 0x1CA0, 0x1CA8, 0x1CB0, 0x1CC0]
    for off in offsets_to_scan:
        raw_vec = scanner.read_mem(weapon_ptr + off, 12)
        if not raw_vec or len(raw_vec) < 12:
            print(f"  0x{off:04X}   | READ FAILED")
            continue
        
        x, y, z = struct.unpack("<fff", raw_vec)
        is_finite = math.isfinite(x) and math.isfinite(y) and math.isfinite(z)
        in_range = is_finite and (abs(x) < 50000.0 and abs(y) < 50000.0 and abs(z) < 50000.0)
        not_zero = is_finite and (x != 0.0 or y != 0.0 or z != 0.0)

        status = "❌ INVALID"
        if in_range and not_zero:
            status = "✅ VALID IMPACT VECTOR" if off == OFF_CCIP_IMPACT else "⚠️ CANDIDATE VECTOR"
        elif is_finite and (x == 0.0 and y == 0.0 and z == 0.0):
            status = "ℹ️ ZERO VECTOR (Idle)"

        print(f"  0x{off:04X}   | {x:12.2f} | {y:12.2f} | {z:12.2f} | {status}")

    print_header("4. LIVE CCIP MONITORING (10 Sec Stream)")
    print(f"{'Time':>8} | {'Impact X':>10} | {'Impact Y':>10} | {'Impact Z':>10} | {'Dist to MyPos':>14} | Status")
    print("-" * 75)

    try:
        for _ in range(20):
            unit_ptr, _ = mul.get_local_team(scanner, base_addr)
            my_pos = mul.get_unit_pos(scanner, unit_ptr)
            raw_impact = scanner.read_mem(weapon_ptr + OFF_CCIP_IMPACT, 12)
            
            if raw_impact and len(raw_impact) == 12:
                ix, iy, iz = struct.unpack("<fff", raw_impact)
                finite = math.isfinite(ix) and math.isfinite(iy) and math.isfinite(iz)
                
                dist_str = "N/A"
                status_str = "OFF / IDLE"

                if finite and (abs(ix) < 50000.0 and abs(iy) < 50000.0 and abs(iz) < 50000.0):
                    if my_pos:
                        dx = ix - my_pos[0]
                        dy = iy - my_pos[1]
                        dz = iz - my_pos[2]
                        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                        dist_str = f"{dist:12.2f}m"
                        if 2.0 < dist < 50000.0:
                            status_str = "🎯 CCIP ACTIVE"

                    t_str = time.strftime("%H:%M:%S")
                    print(f"{t_str:>8} | {ix:10.2f} | {iy:10.2f} | {iz:10.2f} | {dist_str:>14} | {status_str}")
                else:
                    t_str = time.strftime("%H:%M:%S")
                    print(f"{t_str:>8} | {'NaN':>10} | {'NaN':>10} | {'NaN':>10} | {dist_str:>14} | OUT OF BOUNDS")

            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped monitoring.")

    print("\n✅ CCIP & Ballistics Offset Dump completed successfully.")

if __name__ == "__main__":
    dump_ccip_offsets()
