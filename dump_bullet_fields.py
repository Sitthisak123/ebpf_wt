#!/usr/bin/env python3
"""Dump bullet properties around the mass/caliber/cd region to identify fields.

Run: sudo .venv/bin/python3 dump_bullet_fields.py
Switch ammo types in-game to see which fields change.
"""
import sys, os, struct, math, time
sys.path.insert(0, os.path.dirname(__file__))
from src.utils.mul import (
    EBPFScanner, OFF_WEAPON_PTR,
    OFF_BULLET_SPEED, OFF_BULLET_MASS, OFF_BULLET_CALIBER, OFF_BULLET_CD,
    is_valid_ptr,
)

def main():
    scanner = EBPFScanner()
    cgame_base = scanner.cgame_base
    if not cgame_base:
        print("❌ Cannot find cGame base")
        return

    print(f"cGame base: {hex(cgame_base)}")

    # Read weapon ptr
    raw_w = scanner.read_mem(cgame_base + OFF_WEAPON_PTR, 8)
    if not raw_w:
        print("❌ Cannot read weapon ptr")
        return
    w_ptr = struct.unpack("<Q", raw_w)[0]
    if not is_valid_ptr(w_ptr):
        print(f"❌ Invalid weapon ptr: {hex(w_ptr)}")
        return
    print(f"Weapon ptr: {hex(w_ptr)}")
    print()

    # Known offsets
    print("=== KNOWN FIELDS ===")
    known = {
        "speed":   OFF_BULLET_SPEED,
        "mass":    OFF_BULLET_MASS,
        "caliber": OFF_BULLET_CALIBER,
        "cd/len?": OFF_BULLET_CD,
    }
    for name, off in known.items():
        data = scanner.read_mem(w_ptr + off, 4)
        if data:
            val = struct.unpack("<f", data)[0]
            raw_hex = data.hex()
            print(f"  {name:>10} @ 0x{off:04X} = {val:12.6f}  (hex: {raw_hex})")
        else:
            print(f"  {name:>10} @ 0x{off:04X} = READ FAILED")

    # Dump region around mass/caliber (0x20E0 - 0x2110)
    print()
    print("=== MEMORY DUMP: 0x20D0 - 0x2120 ===")
    print(f"{'Offset':>8}  {'HexDump':^35}  {'Float':>12}  {'Int32':>12}  {'Comment'}")
    print("-" * 100)

    start = 0x20D0
    end = 0x2120
    for off in range(start, end, 4):
        data = scanner.read_mem(w_ptr + off, 4)
        if not data:
            print(f"  0x{off:04X}  {'-- -- -- --':^35}  {'N/A':>12}  {'N/A':>12}")
            continue
        f_val = struct.unpack("<f", data)[0]
        i_val = struct.unpack("<i", data)[0]
        hex_str = " ".join(f"{b:02X}" for b in data)

        comment = ""
        if off == OFF_BULLET_SPEED: comment = "<-- speed (muzzle vel)"
        elif off == OFF_BULLET_MASS: comment = "<-- mass"
        elif off == OFF_BULLET_CALIBER: comment = "<-- caliber (diameter)"
        elif off == OFF_BULLET_CD: comment = "<-- cd? or length?"
        elif off == OFF_BULLET_CALIBER + 4: comment = "<-- caliber+4 (length?)"
        elif off == OFF_BULLET_CD + 4: comment = "<-- cd+4"
        elif off == OFF_BULLET_SPEED + 4: comment = "<-- speed+4"

        # Try to guess what it is based on value range
        if math.isfinite(f_val):
            if 0.005 <= f_val <= 200.0 and off >= OFF_BULLET_MASS:
                comment += " [plausible mass/length]"
            if 0.001 <= f_val <= 0.5:
                comment += " [plausible caliber/length_m]"
            if 0.01 <= f_val <= 3.0 and off >= OFF_BULLET_CD:
                comment += " [plausible Cx]"

        print(f"  0x{off:04X}  {hex_str:^35}  {f_val:>12.6f}  {i_val:>12}  {comment}")

    print()
    print("=== INTERPRETATION HINTS ===")
    print("- 'caliber' is the projectile diameter in meters (e.g., 0.057 = 57mm)")
    print("- 'length' (caliberLength) is projectile length in meters (e.g., 0.228 = 228mm)")
    print("- 'Cx' (drag coeff) is typically 0.1-0.5 for most rounds")
    print("- If cd/len? shows a value like 0.15-0.50, it's likely length (not Cx)")
    print("- If cd/len? shows a value like 0.2-0.5, it could be either")
    print()
    print("Switch ammo (1/2/3 key) and re-run to compare values!")


if __name__ == "__main__":
    main()
