import os
import struct
import time
import subprocess
import sys
import math

# 🎯 การตั้งค่า Address จาก Ghidra
GHIDRA_BASE = 0x00400000
DAT_MANAGER = 0x093924e0        # สำหรับดึงรายชื่อยูนิตทั้งหมด
DAT_LOCAL_PLAYER = 0x09394240   # สำหรับดึงตัวเราเอง (Hero)

# 📏 คำนวณ Offset จริงที่ใช้ใน RAM
MANAGER_OFFSET = DAT_MANAGER - GHIDRA_BASE           # 0x8F924E0
LOCAL_PLAYER_OFFSET = DAT_LOCAL_PLAYER - GHIDRA_BASE # 0x8F94240

def get_game_info():
    try:
        pid = int(subprocess.check_output(["pgrep", "aces"]).decode().strip().split('\n')[0])
        with open(f"/proc/{pid}/maps", "r") as f:
            for line in f:
                if "aces" in line:
                    base_addr = int(line.split("-")[0], 16)
                    return pid, base_addr
    except: return None, None
    return None, None

def read_mem(pid, addr, size):
    try:
        with open(f"/proc/{pid}/mem", "rb", 0) as f:
            f.seek(addr)
            return f.read(size)
    except: return b'\x00' * size

def main():
    os.system('clear')
    print("[*] 🛡️ เชื่อมต่อระบบเรดาร์ V.3.1 (Fixed Local Player)")
    
    pid, base_addr = get_game_info()
    if not pid:
        print("❌ ไม่พบเกม aces")
        sys.exit(1)
        
    print(f"✅ Game PID: {pid} | Base: {hex(base_addr)}")
    time.sleep(1)
    
    while True:
        os.system('clear')
        print("🎯 [WAR THUNDER - ULTIMATE ESP RADAR V.3.1]")
        print("-" * 65)
        
        # 👑 1. หาตัวเราเอง (Hero)
        local_ptr_addr = base_addr + LOCAL_PLAYER_OFFSET
        hero_ptr = struct.unpack("<Q", read_mem(pid, local_ptr_addr, 8))[0]
        
        hero_x, hero_y, hero_z = 0.0, 0.0, 0.0
        if hero_ptr != 0:
            # อ่านพิกัดจาก Offset 0xb38 (X, Y, Z)
            hero_pos_data = read_mem(pid, hero_ptr + 0xb38, 12)
            if len(hero_pos_data) == 12:
                hero_x, hero_y, hero_z = struct.unpack("<fff", hero_pos_data)
                print(f"😎 [ตัวเรา] พิกัด -> X: {hero_x:8.2f} | Y: {hero_y:8.2f} | Z: {hero_z:8.2f}")
        else:
            print("😎 [ตัวเรา] กำลังโหลดข้อมูล...")

        print("-" * 65)
        
        # 📡 2. หาศัตรูทั้งหมด (Units)
        manager_ptr_addr = base_addr + MANAGER_OFFSET
        manager_ptr = struct.unpack("<Q", read_mem(pid, manager_ptr_addr, 8))[0]
        
        if manager_ptr != 0:
            array_ptr = struct.unpack("<Q", read_mem(pid, manager_ptr + 0x328, 8))[0]
            unit_count = struct.unpack("<I", read_mem(pid, manager_ptr + 0x338, 4))[0]
            
            valid_units = 0
            for i in range(min(unit_count, 150)):
                unit_ptr = struct.unpack("<Q", read_mem(pid, array_ptr + (i * 8), 8))[0]
                
                # ข้ามถ้าเป็นตัวเราเอง หรือ Pointer ว่าง
                if unit_ptr == 0 or unit_ptr == hero_ptr:
                    continue
                    
                pos_data = read_mem(pid, unit_ptr + 0xb38, 12)
                if len(pos_data) == 12:
                    x, y, z = struct.unpack("<fff", pos_data)
                    if x != 0.0 and -80000.0 < x < 80000.0:
                        valid_units += 1
                        # 📏 คำนวณระยะทาง
                        dist = math.sqrt((x-hero_x)**2 + (y-hero_y)**2 + (z-hero_z)**2)
                        print(f"🚗 [Unit {i:03d}] ห่าง: {dist:7.1f}m | X: {x:8.2f} | Y: {y:8.2f}")
        
        print("-" * 65)
        print(f"✅ อัปเดตเป้าหมาย: {valid_units} คัน")
        time.sleep(0.05)

if __name__ == "__main__":
    main()