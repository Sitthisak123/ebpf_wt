import os
import sys
import struct
import math
import json
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEW_MATRIX_PERSISTENCE_PATH = os.path.join(PROJECT_ROOT, "config", "view_matrix_persistence.json")
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


def _write_persistence(camera_off, matrix_off):
    doc = {
        "camera_off": int(camera_off),
        "matrix_off": int(matrix_off),
        "source": "find_real_matrix_manual_write",
        "updated_by_tool": "find_real_matrix",
        "confidence": 0.95,
        "notes": "Written by tools/find_real_matrix.py",
        "build_fingerprint": _get_binary_fingerprint(),
    }
    os.makedirs(os.path.dirname(VIEW_MATRIX_PERSISTENCE_PATH), exist_ok=True)
    with open(VIEW_MATRIX_PERSISTENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Wrote view persistence: {VIEW_MATRIX_PERSISTENCE_PATH}")
    print(f"    camera_off={hex(camera_off)} matrix_off={hex(matrix_off)}")

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--write-persistence", action="store_true")
    parser.add_argument("--camera-off", type=lambda x: int(x, 0), default=0x670)
    parser.add_argument("--matrix-off", type=lambda x: int(x, 0), default=0x1D0)
    args = parser.parse_args()

    pid = get_game_pid()
    if not pid:
        print("[-] หาโปรเซสเกมไม่เจอ")
        return
        
    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)
    
    cgame = mul.get_cgame_base(scanner, base)
    cam_ptr = mul._read_ptr(scanner, cgame + mul.OFF_CAMERA_PTR)
    
    print("\n==================================================")
    print(" 👁️ THE RAW MATRIX DUMPER (NO FILTERS)")
    print("==================================================")
    
    pointers = [("Direct", cam_ptr), ("Nested", mul._read_ptr(scanner, cam_ptr))]
    
    for name, ptr in pointers:
        if not mul.is_valid_ptr(ptr): continue
        print(f"\n[+] สแกน {name} Pointer: {hex(ptr)}")
        
        # สแกนทุกๆ 0x10 bytes ตั้งแต่ 0x180 ถึง 0x320
        for off in range(0x180, 0x330, 0x10):
            data = scanner.read_mem(ptr + off, 64)
            if not data: continue
            try:
                m = struct.unpack("<16f", data)
                # กรองเฉพาะอันที่มีค่า NaN หรือ Infinity ทิ้งไป
                if any(not math.isfinite(v) or abs(v) > 1000000.0 for v in m): continue
                
                print(f"\n  👉 Offset: 0x{off:X}")
                print(f"     [{m[0]:>9.2f}, {m[1]:>9.2f}, {m[2]:>9.2f}, {m[3]:>9.2f}]")
                print(f"     [{m[4]:>9.2f}, {m[5]:>9.2f}, {m[6]:>9.2f}, {m[7]:>9.2f}]")
                print(f"     [{m[8]:>9.2f}, {m[9]:>9.2f}, {m[10]:>9.2f}, {m[11]:>9.2f}]")
                print(f"     [{m[12]:>9.2f}, {m[13]:>9.2f}, {m[14]:>9.2f}, {m[15]:>9.2f}]")
            except: pass

    if args.write_persistence:
        _write_persistence(args.camera_off, args.matrix_off)

if __name__ == '__main__':
    main()
