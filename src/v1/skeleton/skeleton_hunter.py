import struct
import math
import time
import sys
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import *
from src.utils.scanner import init_dynamic_offsets

def main():
    print("[*] 🕵️‍♂️ เริ่มปฏิบัติการ Skeleton Hunter (V.3 - Local Matrix Hunter)...")
    try:
        pid = get_game_pid()
        scanner = MemoryScanner(pid)
        base_addr = get_game_base_address(pid)
        init_dynamic_offsets(scanner, base_addr)
        
        my_unit, _ = get_local_team(scanner, base_addr)
        if not my_unit:
            print("[-] ไม่เจอตัวละคร")
            return

        print(f"[*] 🔍 สแกนหา Local Skeleton Matrix ในยูนิต {hex(my_unit)}...")
        found_candidates = []
        unit_mem = scanner.read_mem(my_unit, 0x2000)
        if not unit_mem: return

        for i in range(0, len(unit_mem) - 8, 8):
            ptr = struct.unpack_from("<Q", unit_mem, i)[0]
            
            if is_valid_ptr(ptr):
                # ตรวจสอบว่าเป็น AnimChar Component หรือไม่
                # ปกติชั้นแรกจะชี้ไปที่โครงสร้างที่มี Pointer ไปหา Matrix อีกที
                sub_ptr_raw = scanner.read_mem(ptr, 8)
                if not sub_ptr_raw: continue
                sub_ptr = struct.unpack("<Q", sub_ptr_raw)[0]
                
                if is_valid_ptr(sub_ptr):
                    # อ่าน 3 Bones แรก (Body, Turret, Gun)
                    # เช็คว่ามีลักษณะเป็น Local Matrix หรือไม่ (พิกัดใกล้ 0,0,0)
                    test_raw = scanner.read_mem(sub_ptr + 0x30, 12 * 3) # อ่านพิกัด 3 ตัว
                    if test_raw and len(test_raw) == 36:
                        m1 = struct.unpack_from("<fff", test_raw, 0)
                        m2 = struct.unpack_from("<fff", test_raw, 12)
                        
                        # ลักษณะเด่นของ Skeleton Matrix ใน WT:
                        # 1. พิกัด X, Y, Z ของ Body (Index 0) มักจะใกล้ (0, 0, 0) มากๆ
                        # 2. Matrix เป็นแบบ Orthogonal (Scale มักจะเป็น 1.0)
                        if abs(m1[0]) < 1.0 and abs(m1[1]) < 1.0 and abs(m1[2]) < 1.0:
                            # เช็ค Index 1 (Turret) ว่าอยู่เหนือ Body หรือไม่
                            if -2.0 < m2[0] < 2.0 and 0.1 < m2[1] < 4.0:
                                print(f"  [🔥 BINGO!] พบโครงสร้าง Skeleton ที่ Offset {hex(i)}")
                                print(f"     -> Component: {hex(ptr)}")
                                print(f"     -> Matrix Array: {hex(sub_ptr)}")
                                print(f"     -> Local Body: {m1}")
                                print(f"     -> Local Turret: {m2}")
                                
                                # เช็คพิกัดอ้างอิงที่ +0x50 (ตาม Ghidra)
                                origin_raw = scanner.read_mem(ptr + 0x50, 12)
                                if origin_raw:
                                    ox, oy, oz = struct.unpack("<fff", origin_raw)
                                    print(f"     -> Origin Offset (+0x50): {ox:.2f}, {oy:.2f}, {oz:.2f}")
                                
                                found_candidates.append(i)

        if not found_candidates:
            print("[-] ไม่พบ Skeleton ลำดับใดเลย")
        else:
            print("\n✅ สรุป: ใช้ OFF_UNIT_SKELETON =", hex(found_candidates[0]))

    except Exception as e:
        print(f"[-] Error: {e}")

if __name__ == "__main__":
    main()
