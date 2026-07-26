import json
import os
import struct
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return 0
    return struct.unpack("<I", raw)[0]


def main():
    pid = get_game_pid()
    if not pid:
        print("[-] Error: game pid not found")
        return

    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    cgame = mul.get_cgame_base(scanner, base_addr)
    my_unit, _ = mul.get_local_team(scanner, base_addr)
    units = mul.get_all_units(scanner, cgame)

    print("=========================================================================")
    print("🔍 GROUND UNIT SUBCLASS SCANNER (Scanning Unit Struct 0x000 - 0x1200)")
    print("=========================================================================")
    print(f"Total units found: {len(units)}")
    print("-" * 75)

    scanned_units = []
    for u_ptr, is_air in units:
        if is_air:
            continue
        dna = mul.get_unit_detailed_dna(scanner, u_ptr) or {}
        name = dna.get("short_name") or dna.get("name_key") or "Unknown"
        unit_key = dna.get("name_key") or ""
        
        # Collect candidate u32/u64 values across struct
        u32_map = {}
        for off in range(0x0, 0x1200, 4):
            val = read_u32(scanner, u_ptr + off)
            if val in (0x100, 0x200, 0x400, 0x800, 0x1000) or (val & 0x1F00) in (0x100, 0x200, 0x400, 0x800, 0x1000):
                u32_map[hex(off)] = hex(val)

        scanned_units.append({
            "u_ptr": hex(u_ptr),
            "is_me": (u_ptr == my_unit),
            "name": name,
            "unit_key": unit_key,
            "matches_near_f30": u32_map,
        })
        print(f"[{'MY UNIT' if u_ptr == my_unit else 'UNIT'}] {hex(u_ptr)} | Name: {name:<20} | Key: {unit_key}")
        if u32_map:
            print(f"   🎯 Subclass Enum Candidates: {u32_map}")

    print("=========================================================================")

if __name__ == "__main__":
    main()
