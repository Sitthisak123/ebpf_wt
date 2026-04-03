import os
import sys
import struct
import math

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

def main():
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

if __name__ == '__main__':
    main()