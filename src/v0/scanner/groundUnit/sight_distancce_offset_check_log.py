import os
import sys
import struct
import time
from main import MemoryScanner, get_game_pid

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def is_valid_ptr(p): 
    return 0x10000 < p < 0xFFFFFFFFFFFFFFFF

def get_pince_segment(pid, segment_idx=4):
    """ 🌟 ฟังก์ชันพิเศษ: ควานหา Base Address ของ aces[4] ตามแบบฉบับ PINCE """
    segments = []
    try:
        with open(f"/proc/{pid}/maps", "r") as f:
            for line in f:
                parts = line.strip().split()
                # หาเฉพาะ Mapping ที่มาจากไฟล์ aces (ตัดพวก .so ทิ้ง)
                if len(parts) >= 6 and 'aces' in parts[-1] and not '.so' in parts[-1]:
                    start_addr = int(parts[0].split('-')[0], 16)
                    if start_addr not in segments:
                        segments.append(start_addr)
        
        if len(segments) > segment_idx:
            return segments[segment_idx]
        elif segments:
            return segments[-1] # Fallback
    except Exception as e:
        print(f"Error reading maps: {e}")
    return 0

def main():
    pid = get_game_pid()
    if not pid:
        print("[-] ไม่พบโปรเซสเกม!")
        sys.exit(1)
        
    scanner = MemoryScanner(pid)
    
    # ดึง Base Address ของ aces[4]
    aces_4_base = get_pince_segment(pid, 4)
    if aces_4_base == 0:
        print("[-] ไม่สามารถหา aces[4] ได้!")
        sys.exit(1)
    
    SIGHT_POINTER_CHAINS = [
        ("CHAIN 1 [0x76638]", [0x76638, 0x2C20, 0x20F8, 0x1C28]),
        ("CHAIN 2 [0x3830] ", [0x3830,  0xD50,  0x1848, 0x1C28]),
        ("CHAIN 3 [0xC538] ", [0xC538,  0x2C18, 0x1058, 0x1C28]),
        ("CHAIN 4 [0x76640]", [0x76640, 0x2C20, 0x20D8, 0x1C28]),
        ("CHAIN 5 [0x76608]", [0x76608, 0x2BC0, 0x2138, 0x1C28])
    ]
    
    while True:
        try:
            clear_screen()
            print("==================================================")
            print("🔭 WTM TACTICAL: SIGHT POINTER CHAINS CHECKER")
            print(f"🔥 Target Base: aces[4] = {hex(aces_4_base)}")
            print("==================================================")
            
            for name, chain in SIGHT_POINTER_CHAINS:
                try:
                    # 1. เริ่มจาก aces[4] Base Address
                    ptr_addr = aces_4_base + chain[0]
                    raw_ptr = scanner.read_mem(ptr_addr, 8)
                    if not raw_ptr:
                        print(f"[-] {name} : ❌ อ่าน Memory ล้มเหลวที่ Base")
                        continue
                        
                    ptr = struct.unpack("<Q", raw_ptr)[0]
                    
                    # 2. ไต่ตาม Offset
                    valid = True
                    for i, offset in enumerate(chain[1:-1]):
                        if not is_valid_ptr(ptr):
                            valid = False
                            print(f"[-] {name} : ❌ Pointer ตายที่ระดับ {i+1}")
                            break
                        raw_ptr = scanner.read_mem(ptr + offset, 8)
                        if not raw_ptr:
                            valid = False
                            print(f"[-] {name} : ❌ อ่านล้มเหลวที่ระดับ {i+1}")
                            break
                        ptr = struct.unpack("<Q", raw_ptr)[0]
                        
                    if not valid: continue
                        
                    if not is_valid_ptr(ptr):
                        print(f"[-] {name} : ❌ Pointer สุดท้ายพัง")
                        continue
                        
                    # 3. อ่านค่า Float ระยะทาง
                    val_raw = scanner.read_mem(ptr + chain[-1], 4)
                    if val_raw:
                        val = struct.unpack("<f", val_raw)[0]
                        if 0.0 <= val <= 6000.0:
                            print(f"[+] {name} : ✅ {val:.2f} m  <-- 🎯")
                        else:
                            print(f"[?] {name} : ⚠️ ทะลุเกณฑ์ ({val:.2f})")
                    else:
                        print(f"[-] {name} : ❌ อ่านค่า Float ไม่ได้")
                        
                except Exception as e:
                    print(f"[-] {name} : ❌ Error ({e})")
                    
            print("==================================================")
            print("💡 ลองหมุนลูกกลิ้งตั้งศูนย์เล็งในเกม แล้วดูว่า CHAIN ไหน")
            print("   แสดงตัวเลขตรงกับระยะบนจอเป๊ะๆ (กด Ctrl+C เพื่อหยุด)")
            time.sleep(0.05) 
            
        except KeyboardInterrupt:
            print("\n[!] จบภารกิจตรวจสอบ")
            break

if __name__ == '__main__':
    main()