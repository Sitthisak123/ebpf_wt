import os
import sys
import struct
import math
import time
from collections import Counter

# นำเข้าเครื่องมือจากระบบเดิม
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_cgame_base, get_local_team

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def main():
    print("[*] กำลังเตรียมระบบ DNA Tick Analyzer...")
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    
    try:
        scanner = MemoryScanner(pid)
    except PermissionError:
        print("[-] Error: สิทธิ์ไม่พอ! รันด้วย sudo นะครับ")
        sys.exit(1)
        
    init_dynamic_offsets(scanner, base_address)
    
    print("[*] กำลังค้นหายูนิตของท่าน (โปรดขับเครื่องบินให้ขยับเล็กน้อย)...")
    my_unit = 0
    while not my_unit:
        my_unit, _ = get_local_team(scanner, base_address)
        time.sleep(0.5)

    print(f"[+] เจอตัวแล้ว! Unit Ptr: {hex(my_unit)}")
    
    # ==========================================
    # 🧬 1. สแกนหา Offsets ทุกตัวจาก DNA
    # ==========================================
    print("[*] กำลังสแกนหา Offsets จาก DNA ของท่าน...")
    air_vel_dna = "0F 10 ? 18 03 00 00 0F 10 ? 24 03 00 00"
    found_offsets = scanner.find_all_struct_offsets(air_vel_dna, 3)
    
    if not found_offsets:
        print("[-] ❌ ไม่พบ Offset ใดๆ จาก DNA นี้เลยครับ")
        sys.exit(1)
        
    # กรองเอาเฉพาะค่าที่ไม่ซ้ำกัน
    unique_offsets = list(set(found_offsets))
    print(f"[+] พบ Offsets ทั้งหมด {len(unique_offsets)} รายการ: {[hex(x) for x in unique_offsets]}")
    time.sleep(2)
    
    # ==========================================
    # 🎯 2. สร้างรายการทดสอบ
    # ==========================================
    CANDIDATES = []
    for v_off in unique_offsets:
        if 0 < v_off < 0x2000:  # กรองค่าที่เกินจริง
            # ทดสอบจับคู่กับ Pointer 0x18 (เดิม) และ 0x22B8 (Visual) เผื่อไว้
            CANDIDATES.append((0x0018, v_off, "FLOAT"))
            CANDIDATES.append((0x22B8, v_off, "FLOAT"))
    
    # สร้างระบบบันทึกไฟล์
    dump_dir = os.path.join(os.getcwd(), "dump")
    os.makedirs(dump_dir, exist_ok=True)
    time_str = time.strftime("%Y%m%d_%H%M%S")
    csv_file = os.path.join(dump_dir, f"dna_tick_analyzer_{time_str}.csv")
    
    # เขียน Header CSV
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
    
    # ==========================================
    # 🚀 3. ลูปตรวจจับ Tick Rate (Hz)
    # ==========================================
    try:
        while True:
            curr_time = time.time()
            unit_data = scanner.read_mem(my_unit, 0x2500)
            
            if unit_data:
                for i, (p_off, v_off, dtype) in enumerate(CANDIDATES):
                    try:
                        ptr_val = struct.unpack_from("<Q", unit_data, p_off)[0]
                        if ptr_val > 0:
                            vel_data = scanner.read_mem(ptr_val + v_off, 12)
                            if vel_data:
                                vx, vy, vz = struct.unpack("<fff", vel_data)
                                
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
            
            # สรุปผลและบันทึกลงหน้าจอทุกๆ 1 วินาที
            if curr_time - last_report_time >= 1.0:
                clear_screen()
                print(f"=== 🧬 LIVE DNA TICK ANALYZER ===")
                print(f"Unit: {hex(my_unit)} | ค้นพบ Offsets จาก DNA: {len(unique_offsets)} ตัว")
                print("-" * 60)
                
                csv_row = [f"{curr_time:.2f}"]
                
                for i, (p_off, v_off, dtype) in enumerate(CANDIDATES):
                    hz = stats[i]["changes"]
                    spd = stats[i]["speed"]
                    
                    # ไฮไลต์สี (ไฟลุก = ลื่นไหล 38Hz+, เต่า = กระตุก 4Hz)
                    marker = "🔥 (SMOOTH!)" if hz > 30 else "🐢 (Physics)" if hz > 0 else "❌"
                    
                    print(f"Ptr: 0x{p_off:04X} -> Vel: 0x{v_off:04X} | Tick: {hz:3d} Hz {marker} | Spd: {spd:6.2f}")
                    
                    csv_row.append(str(hz))
                    csv_row.append(f"{spd:.4f}")
                    stats[i]["changes"] = 0
                
                with open(csv_file, "a", encoding="utf-8") as f:
                    f.write(",".join(csv_row) + "\n")
                    
                last_report_time = curr_time
                
            time.sleep(0.005) # ~200Hz Loop
            
    except KeyboardInterrupt:
        print("\n[+] บันทึกข้อมูลและปิดโปรแกรมเรียบร้อยแล้ว!")
        sys.exit(0)

if __name__ == "__main__":
    main()