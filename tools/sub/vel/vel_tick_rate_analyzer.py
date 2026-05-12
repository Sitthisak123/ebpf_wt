import os
import sys
import struct
import math
import time

# นำเข้าเครื่องมือจากระบบเดิม
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_cgame_base, get_local_team

# 🎯 รายชื่อ 20 ผู้ต้องสงสัยที่ท่านนายพลคัดกรองมา
CANDIDATES = [
    (0x0018, 0x0318, "FLOAT"),
    (0x0018, 0x0358, "FLOAT"),
    (0x0018, 0x0398, "FLOAT"),
    (0x0018, 0x03D8, "FLOAT"),
    (0x0018, 0x0418, "FLOAT"),
    (0x0018, 0x0458, "FLOAT"),
    (0x0018, 0x0498, "FLOAT"),
    (0x0018, 0x04D8, "FLOAT"),
    (0x0018, 0x0518, "FLOAT"),
    (0x0D10, 0x0068, "DOUBLE"),
    (0x0D10, 0x00C8, "DOUBLE"),
    (0x0D10, 0x00D0, "DOUBLE"),
    (0x0D18, 0x0068, "DOUBLE"),
    (0x0D18, 0x00C8, "DOUBLE"),
    (0x0D18, 0x00D0, "DOUBLE"),
    (0x22B8, 0x0E50, "FLOAT"),
    (0x22C0, 0x0D78, "FLOAT"),
    (0x22C8, 0x0D78, "FLOAT"),
    (0x23A8, 0x0E50, "FLOAT"),
    (0x23B0, 0x0E50, "FLOAT")
]

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def main():
    print("[*] กำลังเตรียมระบบ Blackbox Tick Analyzer...")
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    
    try:
        scanner = MemoryScanner(pid)
    except PermissionError:
        print("[-] Error: สิทธิ์ไม่พอ! รันด้วย sudo นะครับ")
        sys.exit(1)
        
    init_dynamic_offsets(scanner, base_address)
    cgame_base = get_cgame_base(scanner, base_address)
    
    print("[*] กำลังค้นหายูนิตของท่าน (โปรดขับรถถัง/เครื่องบินให้ขยับเล็กน้อย)...")
    my_unit = 0
    while not my_unit:
        my_unit, _ = get_local_team(scanner, base_address)
        time.sleep(0.5)

    print(f"[+] เจอตัวแล้ว! Unit Ptr: {hex(my_unit)}")
    
    # สร้างระบบบันทึกไฟล์
    dump_dir = os.path.join(os.getcwd(), "dump")
    os.makedirs(dump_dir, exist_ok=True)
    time_str = time.strftime("%Y%m%d_%H%M%S")
    csv_file = os.path.join(dump_dir, f"offset_tick_analyzer_{time_str}.csv")
    
    # เขียน Header ของไฟล์ CSV
    with open(csv_file, "w", encoding="utf-8") as f:
        headers = ["Time"]
        for p_off, v_off, _ in CANDIDATES:
            headers.append(f"Hz_0x{p_off:X}_0x{v_off:X}")
            headers.append(f"Spd_0x{p_off:X}_0x{v_off:X}")
        f.write(",".join(headers) + "\n")

    # ตัวแปรเก็บสถิติ
    stats = {i: {"changes": 0, "last_val": None, "speed": 0.0} for i in range(len(CANDIDATES))}
    last_report_time = time.time()
    
    clear_screen()
    
    try:
        while True:
            curr_time = time.time()
            
            # 1. ดูดข้อมูล Memory ก้อนใหญ่ก้อนเดียวเพื่อความเร็ว
            unit_data = scanner.read_mem(my_unit, 0x2500)
            if unit_data:
                # 2. แกะค่าผู้ต้องสงสัยทั้ง 20 รายการ
                for i, (p_off, v_off, dtype) in enumerate(CANDIDATES):
                    try:
                        ptr_val = struct.unpack_from("<Q", unit_data, p_off)[0]
                        if ptr_val > 0:
                            vel_data = scanner.read_mem(ptr_val + v_off, 24 if dtype == "DOUBLE" else 12)
                            if vel_data:
                                if dtype == "FLOAT":
                                    vx, vy, vz = struct.unpack("<fff", vel_data)
                                else:
                                    vx, vy, vz = struct.unpack("<ddd", vel_data)
                                
                                # ปัดทศนิยมตำแหน่งที่ 4 เพื่อกรอง Noise ของ Memory
                                val = (round(vx, 4), round(vy, 4), round(vz, 4))
                                stats[i]["speed"] = math.sqrt(vx**2 + vy**2 + vz**2)
                                
                                # ถ้ายูนิตขยับ (ความเร็ว > 0) และค่าเปลี่ยนจากเฟรมที่แล้ว
                                if stats[i]["speed"] > 0.05:
                                    if stats[i]["last_val"] is not None and val != stats[i]["last_val"]:
                                        stats[i]["changes"] += 1
                                stats[i]["last_val"] = val
                    except Exception:
                        pass
            
            # 3. สรุปผลและบันทึกลงไฟล์ทุกๆ 1 วินาที
            if curr_time - last_report_time >= 1.0:
                clear_screen()
                print(f"=== 🕵️‍♂️ LIVE TICK RATE ANALYZER ===")
                print(f"Unit: {hex(my_unit)} | บันทึกไฟล์ที่: {csv_file}")
                print("-" * 65)
                
                csv_row = [f"{curr_time:.2f}"]
                
                for i, (p_off, v_off, dtype) in enumerate(CANDIDATES):
                    hz = stats[i]["changes"]
                    spd = stats[i]["speed"]
                    
                    # ไฮไลต์สีให้ดูง่าย (ถ้า > 50 Hz แสดงว่าเจอของดี!)
                    marker = "🔥" if hz > 40 else "🐢" if hz > 0 else "❌"
                    
                    print(f"[{i:2d}] Move: 0x{p_off:04X} -> Vel: 0x{v_off:04X} ({dtype:6s}) | Tick: {hz:3d} Hz {marker} | Spd: {spd:6.2f}")
                    
                    csv_row.append(str(hz))
                    csv_row.append(f"{spd:.4f}")
                    
                    # รีเซ็ตตัวนับ
                    stats[i]["changes"] = 0
                
                # เขียนลงไฟล์
                with open(csv_file, "a", encoding="utf-8") as f:
                    f.write(",".join(csv_row) + "\n")
                    
                last_report_time = curr_time
                
            # หน่วงเวลาลูปให้อ่านค่าได้ที่ประมาณ 150-200 Hz
            time.sleep(0.005)
            
    except KeyboardInterrupt:
        print("\n[+] บันทึกข้อมูลและปิดโปรแกรมเรียบร้อยแล้ว!")
        sys.exit(0)

if __name__ == "__main__":
    main()