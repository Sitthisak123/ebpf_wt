import os
import sys
import time
import math
import csv

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_cgame_base, get_local_team, get_all_units, get_unit_pos, get_air_velocity

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def main():
    clear_screen()
    print("==================================================")
    print("🛫 WTM TELEMETRY LOGGER (RAW DATA DUMPER)")
    print("==================================================")
    
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    
    try:
        scanner = MemoryScanner(pid)
    except PermissionError:
        print("[-] ❌ สิทธิ์ไม่พอ! รันด้วย sudo ครับ")
        sys.exit(1)
        
    print("[*] กำลังเชื่อมต่อระบบเรดาร์และยืนยัน Offset...")
    init_dynamic_offsets(scanner, base_address)
    
    cgame_base = get_cgame_base(scanner, base_address)
    if not cgame_base:
        print("[-] ❌ หา CGame Base ไม่เจอ")
        return

    print("[*] กำลังค้นหายูนิตของท่าน...")
    my_unit = 0
    my_team = -1
    while not my_unit:
        my_unit, my_team = get_local_team(scanner, base_address)
        time.sleep(0.5)
    print(f"[+] เจอตัวแล้ว! Unit Ptr: {hex(my_unit)} | Team: {my_team}")

    # สร้างไฟล์ CSV สำหรับเก็บข้อมูล
    filename = f"raw_telemetry_{int(time.time())}.csv"
    
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        # กำหนดหัวตาราง (Header)
        writer.writerow([
            "Timestamp", "Target_Ptr", 
            "Pos_X", "Pos_Y", "Pos_Z", 
            "Vel_X", "Vel_Y", "Vel_Z", "Speed_mps"
        ])
        
        print(f"\n[+] 🔴 เริ่มการบันทึกข้อมูลกล่องดำลงไฟล์: {filename}")
        print("[!] กด Ctrl+C เพื่อหยุดบันทึก...")
        print("-" * 50)
        
        try:
            start_time = time.time()
            record_count = 0
            
            while True:
                current_time = time.time() - start_time
                
                # ดึงข้อมูลยูนิตทั้งหมด
                all_units = get_all_units(scanner, cgame_base)
                
                # คัดกรองเฉพาะ "เครื่องบินศัตรู"
                enemy_airs = [u for u in all_units if u[1] == True] # u[1] คือ is_air
                
                if enemy_airs:
                    # สมมติว่าโฟกัสที่เป้าหมายแรกที่เจอ (เพื่อไม่ให้ข้อมูลปนกัน)
                    target_ptr = enemy_airs[0][0]
                    
                    pos = get_unit_pos(scanner, target_ptr)
                    vel = get_air_velocity(scanner, target_ptr)
                    
                    if pos and vel:
                        px, py, pz = pos
                        vx, vy, vz = vel
                        speed = math.sqrt(vx**2 + vy**2 + vz**2)
                        
                        # บันทึกข้อมูลลง CSV
                        writer.writerow([
                            f"{current_time:.4f}", hex(target_ptr),
                            f"{px:.4f}", f"{py:.4f}", f"{pz:.4f}",
                            f"{vx:.4f}", f"{vy:.4f}", f"{vz:.4f}", f"{speed:.4f}"
                        ])
                        
                        record_count += 1
                        if record_count % 30 == 0:
                            print(f"  -> 🔴 กำลังบันทึก... ({record_count} records) | Target: {hex(target_ptr)} | Speed: {speed:.1f} m/s")
                
                # หน่วงเวลา 0.02 วินาที (บันทึกที่ความถี่ประมาณ 50Hz)
                time.sleep(0.02)
                
        except KeyboardInterrupt:
            print(f"\n[+] 🛑 หยุดการบันทึก! บันทึกข้อมูลไปทั้งหมด {record_count} รายการ")
            print(f"[*] ข้อมูลถูกบันทึกไว้ที่ไฟล์: {os.path.abspath(filename)}")

if __name__ == "__main__":
    main()