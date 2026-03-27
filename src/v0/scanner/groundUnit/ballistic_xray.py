import struct
import math
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import get_cgame_base, OFF_WEAPON_PTR, is_valid_ptr

def main():
    print("[*] 🔫 ปฏิบัติการ The Ballistic X-Ray (สแกนหา Mass & Drag ของแท้)...")
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    cgame_base = get_cgame_base(scanner, base_addr)

    w_ptr_raw = scanner.read_mem(cgame_base + OFF_WEAPON_PTR, 8)
    if not w_ptr_raw: 
        print("[-] ไม่พบ Pointer อาวุธ")
        return
        
    w_ptr = struct.unpack("<Q", w_ptr_raw)[0]
    if not is_valid_ptr(w_ptr):
        print("[-] Pointer อาวุธพัง")
        return
        
    print(f"[*] 🎯 Weapon Pointer: {hex(w_ptr)}")
    
    # อ่านข้อมูลแถวๆ 0x2000 - 0x2100 (โซนข้อมูล Ballistics)
    data = scanner.read_mem(w_ptr + 0x2000, 0x100)
    if not data: return
    
    print("\n🔍 [ข้อมูลสเปคกระสุนรอบๆ ความเร็ว]")
    print("-" * 50)
    for i in range(0, len(data), 4):
        val = struct.unpack_from("<f", data, i)[0]
        # กรองเอาเฉพาะตัวเลขที่มีค่าสมเหตุสมผล
        if math.isfinite(val) and 0.0001 < abs(val) < 5000.0:
            offset = 0x2000 + i
            marker = ""
            if offset == 0x2048: marker = " <--- [SPEED] ความเร็วต้น (m/s)"
            print(f"Offset: {hex(offset):<8} | ค่า (Float) = {val:.4f}{marker}")
            
    print("-" * 50)
    print("💡 คำแนะนำ: มองหาเลขน้ำหนักกระสุน (เช่น 2.09, 15.5) และค่า Drag (เช่น 0.02, 0.35) จากตารางด้านบนครับ")

if __name__ == "__main__":
    main()