import os
import sys
import struct
import time
import math
from main import MemoryScanner, get_game_pid, get_game_base_address

# 🚨 นำเข้าฟังก์ชันจาก mul.py
from src.untils.mul import get_cgame_base, get_all_units, is_valid_ptr

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def main():
    pid = get_game_pid()
    if not pid:
        print("[-] ไม่พบโปรเซสเกม!")
        sys.exit(1)
        
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    
    # 🎯 สร้างเซ็ตของ Offset ที่เป็นไปได้ทั้งหมด (ตั้งแต่ 0x200 ถึง 0x400 สแกนทีละ 4 bytes)
    possible_offsets = set(range(0x200, 0x400, 4))
    
    last_v = None
    target_locked = False
    
    while True:
        try:
            cgame_base = get_cgame_base(scanner, base_addr)
            if cgame_base == 0: continue
            
            all_units = get_all_units(scanner, cgame_base)
            air_units = [u for u in all_units if u[1] == True]
            
            if not air_units:
                clear_screen()
                print("[-] กำลังรอเครื่องบินเกิด...")
                time.sleep(0.5)
                continue
                
            # โฟกัสไปที่เครื่องบินลำแรกเสมอ
            target_ptr = air_units[0][0]
            mov_raw = scanner.read_mem(target_ptr + 0x18, 8) # OFF_AIR_MOVEMENT
            if not mov_raw: continue
            mov_ptr = struct.unpack("<Q", mov_raw)[0]
            if not is_valid_ptr(mov_ptr): continue
            
            # ดึงความเร็วปัจจุบัน (Velocity 0x318)
            vel_raw = scanner.read_mem(mov_ptr + 0x318, 12)
            if not vel_raw: continue
            vx, vy, vz = struct.unpack("<fff", vel_raw)
            
            # ดึงก้อน Memory ต้องสงสัยทั้งหมดมาวิเคราะห์ทีเดียว (512 bytes)
            mem_block = scanner.read_mem(mov_ptr + 0x200, 512)
            if not mem_block: continue
            
            if last_v is not None:
                # คำนวณความเร่ง เพื่อดูว่าเครื่องบิน "บินตรง" หรือ "กำลังเลี้ยว"
                dvx = vx - last_v[0]
                dvy = vy - last_v[1]
                dvz = vz - last_v[2]
                accel_mag = math.sqrt(dvx**2 + dvy**2 + dvz**2)
                
                is_straight = accel_mag < 0.05  # บินตรงแหน่ว
                is_turning = accel_mag > 1.5    # เลี้ยวแรงมาก
                
                # 🔪 THE FILTER: ล้างบาง Offset ที่ละเมิดกฎฟิสิกส์
                to_remove = set()
                for offset in possible_offsets:
                    local_off = offset - 0x200
                    if local_off + 12 > len(mem_block): continue
                    
                    wx, wy, wz = struct.unpack_from("<fff", mem_block, local_off)
                    
                    # ถ้าเจอค่า NaN หรือ Inf หรือขยะ คัดทิ้งทันที!
                    if not (math.isfinite(wx) and math.isfinite(wy) and math.isfinite(wz)):
                        to_remove.add(offset)
                        continue
                        
                    w_mag = math.sqrt(wx**2 + wy**2 + wz**2)
                    
                    if is_straight:
                        # กฎข้อ 1: บินตรง Omega ต้องเกือบศูนย์ ถ้าทะลุ 0.1 คือของปลอม
                        if w_mag > 0.1: 
                            to_remove.add(offset)
                            
                    elif is_turning:
                        # กฎข้อ 2: เลี้ยวแรง Omega ต้องมีค่า แต่ต้องไม่เว่อร์เกินความเป็นจริงของเครื่องบิน
                        if w_mag < 0.1 or w_mag > 20.0:
                            to_remove.add(offset)
                            
                # อัปเดตรายชื่อผู้เข้ารอบ
                possible_offsets -= to_remove
                
            last_v = (vx, vy, vz)
            
            # ==========================================
            # 🖥️ หน้าจอแสดงผลแบบสดๆ
            # ==========================================
            clear_screen()
            print("===============================================================")
            print("🌪️ THE OMEGA HUNTER (ANGULAR VELOCITY SCANNER)")
            print("===============================================================")
            print(f"✈️ TARGET PTR : {hex(target_ptr)}")
            print(f"🚀 VELOCITY   : X={vx:7.2f} | Y={vy:7.2f} | Z={vz:7.2f}")
            print(f"🎯 ผู้ต้องสงสัยที่เหลือรอด: {len(possible_offsets)} Offsets -> {[hex(o) for o in possible_offsets]}")
            print("-" * 63)
            
            # โชว์รายชื่อผู้เข้ารอบสูงสุด 15 อันดับ
            for off in sorted(list(possible_offsets))[:15]:
                local_off = off - 0x200
                if local_off + 12 <= len(mem_block):
                    wx, wy, wz = struct.unpack_from("<fff", mem_block, local_off)
                    print(f"   [0x{off:03X}] : X={wx:8.3f} | Y={wy:8.3f} | Z={wz:8.3f}")
            
            print("-" * 63)
            print("💡 ยุทธวิธีสแกน:")
            print(" 1. เข้า Test Drive เลือกเครื่องบินขับไล่")
            print(" 2. ปล่อยเมาส์ 'บินตรงๆ' ประมาณ 3 วินาที (ขยะจะหายไปครึ่งนึง)")
            print(" 3. หักเมาส์ควงสว่าน 'Roll' หรือ 'Pitch' สุดแรง! (ขยะจะหายไปอีก)")
            print(" 4. ทำสลับไปมาจนกว่า 'ผู้ต้องสงสัย' จะเหลือแค่ 1-2 บรรทัด!!")
            
            time.sleep(0.05) # สแกนรัวๆ 20 รอบต่อวินาที
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            pass

if __name__ == '__main__':
    main()