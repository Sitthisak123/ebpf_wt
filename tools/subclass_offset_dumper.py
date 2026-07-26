import os
import sys
import struct
import math
import time
import json
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

SUBCLASS_PERSISTENCE_PATH = os.path.join(PROJECT_ROOT, "config", "ground_subclass_persistence.json")
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


def read_u32(scanner, addr):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return 0
    return struct.unpack("<I", raw)[0]


def write_persistence(subclass_off, subclass_mask=0x1F00, confidence=0.95):
    doc = {
        "subclass_off": int(subclass_off),
        "subclass_mask": int(subclass_mask),
        "source": "subclass_offset_dumper",
        "updated_by_tool": "subclass_offset_dumper",
        "confidence": confidence,
        "notes": "Auto-dumper for Ground Unit Subclass Enum Offsets",
        "build_fingerprint": _get_binary_fingerprint(),
        "layout": {
            "0x100": "LIGHT_TANK",
            "0x200": "MEDIUM_TANK",
            "0x400": "HEAVY_TANK",
            "0x800": "TANK_DESTROYER",
            "0x1000": "SPAA"
        }
    }
    os.makedirs(os.path.dirname(SUBCLASS_PERSISTENCE_PATH), exist_ok=True)
    with open(SUBCLASS_PERSISTENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"[+] Wrote Subclass Persistence -> {SUBCLASS_PERSISTENCE_PATH}")
    print(f"    subclass_off={hex(subclass_off)} | mask={hex(subclass_mask)} | conf={confidence}")


def find_subclass_offset(scanner, cgame_ptr):
    units = mul.get_all_units(scanner, cgame_ptr)
    if not units:
        return None

    valid_enums = {0x100, 0x200, 0x400, 0x800, 0x1000}
    candidate_maps = {}

    for u_ptr, is_air in units:
        if is_air:
            continue
        for off in range(0xE00, 0x1100, 4):
            val = read_u32(scanner, u_ptr + off)
            masked = val & 0x1F00
            if masked in valid_enums:
                if off not in candidate_maps:
                    candidate_maps[off] = set()
                candidate_maps[off].add(masked)

    if not candidate_maps:
        return None

    best_off = max(candidate_maps, key=lambda o: (len(candidate_maps[o]), 1 if o == 0xF48 else 0))
    return best_off



def main():
    parser = argparse.ArgumentParser(description="Ground Subclass Offset Dumper & Persistence Generator")
    parser.add_argument("--watch", action="store_true", help="Watch mode: continuously poll memory and update persistence")
    args = parser.parse_args()

    print("================================================================================")
    print("🚀 GROUND SUBCLASS OFFSET DUMPER")
    print("================================================================================")

    pid = get_game_pid()
    if not pid:
        print("[-] Game process not found")
        return

    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    if not cgame_ptr:
        print("[-] CGame Base not found")
        return

    print(f"[+] Connected to WarThunder PID: {pid} | Base: {hex(base_addr)} | CGame: {hex(cgame_ptr)}")

    while True:
        subclass_off = find_subclass_offset(scanner, cgame_ptr)
        if subclass_off:
            print(f"[+] Found Subclass Enum Offset: {hex(subclass_off)} (3912 decimal)")
            write_persistence(subclass_off, 0x1F00, confidence=0.95)
        else:
            print("[-] Could not find matching Subclass Offset in active units")

        if not args.watch:
            break

        time.sleep(2.0)


if __name__ == "__main__":
    main()
