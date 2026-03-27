import os
import sys
import struct
import math
import time
from main import MemoryScanner, get_game_pid

def main():
    pid = get_game_pid()
    scanner = MemoryScanner(pid)
    
    # 🎯 สร้างรายการเป้าหมายจาก OMNI-SCANNER
    # รูปแบบ: (Unit_Ptr, Move_Ptr_Offset, Vel_Offset, Data_Type)
    scan_results = [
        # --- Unit: 0x4dabbb60 ---
        (0x4dabbb60, 0x0AD8, 0x0000, "FLOAT"),
        (0x4dabbb60, 0x0AD8, 0x0040, "FLOAT"),
        (0x4dabbb60, 0x1338, 0x0000, "FLOAT"),
        (0x4dabbb60, 0x1338, 0x0040, "FLOAT"),
        # --- Unit: 0x4dccbab0 ---
        (0x4dccbab0, 0x0D10, 0x0068, "DOUBLE"),
        (0x4dccbab0, 0x0D10, 0x00C8, "DOUBLE"),
        (0x4dccbab0, 0x0D10, 0x00D0, "DOUBLE"),
        (0x4dccbab0, 0x0D18, 0x0068, "DOUBLE"),
        (0x4dccbab0, 0x0D18, 0x00C8, "DOUBLE"),
        (0x4dccbab0, 0x0D18, 0x00D0, "DOUBLE")
    ]

    os.system("clear")
    
    while True:
        output_lines = []
        for unit_ptr, move_ptr_off, vel_off, dtype in scan_results:
            try:
                # 1. อ่าน Memory 8 bytes เพื่อเอา Pointer เป้าหมายออกมา
                ptr_data = scanner.read_mem(unit_ptr + move_ptr_off, 8)
                if not ptr_data or len(ptr_data) != 8:
                    output_lines.append(f"U:{hex(unit_ptr)[-6:]} | P:0x{move_ptr_off:04X} | V:0x{vel_off:04X} | {'BAD PTR':>10} | {'-':>12}")
                    continue
                    
                target_ptr = struct.unpack("<Q", ptr_data)[0]
                
                # ถ้า Pointer เป็น 0 หรือไม่ใช่ Address ที่ถูกต้อง
                if target_ptr == 0:
                    output_lines.append(f"U:{hex(unit_ptr)[-6:]} | P:0x{move_ptr_off:04X} | V:0x{vel_off:04X} | {'NULL PTR':>10} | {'-':>12}")
                    continue

                # 2. คำนวณ Final Address และกำหนดขนาดที่จะอ่าน
                final_addr = target_ptr + vel_off
                read_size = 24 if dtype == "DOUBLE" else 12
                
                # 3. อ่านค่า Velocity
                vel_data = scanner.read_mem(final_addr, read_size)
                
                if vel_data and len(vel_data) == read_size:
                    if dtype == "FLOAT":
                        vx, vy, vz = struct.unpack("<fff", vel_data)
                    else:
                        vx, vy, vz = struct.unpack("<ddd", vel_data)
                    
                    speed = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                    
                    if not math.isfinite(speed) or speed > 5000:
                        v1 = struct.unpack("<f" if dtype == "FLOAT" else "<d", vel_data[:4 if dtype == "FLOAT" else 8])[0]
                        line = f"U:{hex(unit_ptr)[-6:]} | P:0x{move_ptr_off:04X} | V:0x{vel_off:04X} | {v1:>10.2f} | {'NaN/Inf':>12}"
                    else:
                        line = f"U:{hex(unit_ptr)[-6:]} | P:0x{move_ptr_off:04X} | V:0x{vel_off:04X} | {vx:>10.1f} | {speed:>12.1f}"
                        
                    # ไฮไลต์ถ้า Speed มีค่าสมเหตุสมผล (เช่น 10 - 1500 km/h)
                    if 10.0 < speed < 1500.0:
                        line = f"\033[92m{line}  <-- MATCH!\033[0m"
                        
                    output_lines.append(line)
                else:
                    output_lines.append(f"U:{hex(unit_ptr)[-6:]} | P:0x{move_ptr_off:04X} | V:0x{vel_off:04X} | {'MEM ERR':>10} | {'-':>12}")
            except Exception as e:
                output_lines.append(f"U:{hex(unit_ptr)[-6:]} | P:0x{move_ptr_off:04X} | V:0x{vel_off:04X} | {'EXCEPTION':>10} | {'-':>12}")

        # อัปเดตหน้าจอ
        sys.stdout.write("\033[H\033[J") 
        print("=========================================================================================")
        print(" 🚀 DYNAMIC VELOCITY HUNTER - Monitoring Pointer Chains")
        print("=========================================================================================")
        print(f"{'UNIT':<8} | {'MOVE_PTR':<8} | {'VEL_OFF':<8} | {'X_VAL':>10} | {'SPEED (KM/H)':>12}")
        print("-" * 90)
        
        for l in output_lines:
            print(l)
        
        time.sleep(0.1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.stdout.write("\033[2J\033[H")
        print("[*] Exiting Dynamic Velocity Hunter...")
        sys.exit(0)