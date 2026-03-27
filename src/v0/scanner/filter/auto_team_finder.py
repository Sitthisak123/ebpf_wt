import struct
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import get_cgame_base, get_all_units

def main():
    print("[*] 🧬 เริ่มการสแกนหา Team Offset...")
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    cgame_base = get_cgame_base(scanner, base_addr)
    
    # 1. ดึง Pointer รถของเรา (Local Player)
    DAT_CONTROLLED_UNIT = 0x9809ac8
    my_unit_raw = scanner.read_mem(base_addr + (DAT_CONTROLLED_UNIT - 0x400000), 8)
    if not my_unit_raw:
        print("[-] ไม่พบรถของคุณ (กรุณาเข้า Test Drive)")
        return
    my_unit = struct.unpack("<Q", my_unit_raw)[0]
    
    print(f"[*] 🟢 รถของเรา: {hex(my_unit)}")
    
    # 2. ดึงรถศัตรูทั้งหมด
    units = get_all_units(scanner, cgame_base)
    enemy_units = [u[0] for u in units if u[0] != my_unit]
    print(f"[*] 🔴 พบรถเป้าหมาย: {len(enemy_units)} คัน")
    
    # 3. สแกนหา Team Offset (เปรียบเทียบข้อมูล 0xF00 - 0x1000)
    my_data = scanner.read_mem(my_unit + 0xF00, 0x100)
    if not my_data: return
    
    found = False
    for i in range(0x100):
        my_team_val = my_data[i]
        
        # กฎของ War Thunder: ทีมผู้เล่นมักจะเป็น 1 และศัตรูมักจะเป็น 2 (หรือสลับกัน)
        if my_team_val in [1, 2]: 
            is_valid = True
            enemy_team_val = -1
            
            # สุ่มตรวจศัตรู 5 คัน (เอาคันกลางๆ แถวๆ Index 5-10 เพราะคันแรกๆ อาจเป็นซาก)
            for e_ptr in enemy_units[5:10]: 
                e_data = scanner.read_mem(e_ptr + 0xF00, 0x100)
                if not e_data: continue
                e_val = e_data[i]
                
                # ถ้าศัตรูไม่ใช่ทีม 1 หรือ 2 หรือดันอยู่ทีมเดียวกับเรา = ไม่ใช่ Team Offset
                if e_val not in [1, 2] or e_val == my_team_val:
                    is_valid = False
                    break
                enemy_team_val = e_val
                
            if is_valid and enemy_team_val != -1:
                print(f"✅ BINGO! เจอ Team Offset ที่: {hex(0xF00 + i)} (ทีมเรา: {my_team_val}, ทีมศัตรู: {enemy_team_val})")
                found = True
                break
                
    if not found:
        print("[-] สแกนไม่เจอ! (ลองขยับรถไปใกล้ๆ เป้าหมายแล้วรันใหม่ครับ)")

if __name__ == "__main__":
    main()