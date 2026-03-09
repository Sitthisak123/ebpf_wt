import os
import sys
import time
import struct
import subprocess

# 🎯 ตั้งค่าหน้าจอของคุณ
screen_w = 2560
screen_h = 1440

# 🚨 ดึง (Import) ฟังก์ชันทั้งหมด รวมถึง world_to_screen ด้วย!
try:
    from src.untils.mul import get_cgame_base, get_view_matrix, get_unit_pos, world_to_screen
except ImportError:
    print("[-] Error: หาไฟล์ src/untils/mul.py ไม่เจอ หรือลืมใส่ฟังก์ชัน world_to_screen ไว้ในนั้น!")
    sys.exit(1)

# ==========================================
# 🛠️ คลาสสำหรับอ่าน Memory (ทำหน้าที่เป็น Scanner)
# ==========================================
class MemoryScanner:
    def __init__(self, pid):
        self.pid = pid
        self.mem_fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)

    def read_mem(self, address, size):
        try:
            os.lseek(self.mem_fd, address, os.SEEK_SET)
            return os.read(self.mem_fd, size)
        except Exception:
            return None
            
    def __del__(self):
        try:
            os.close(self.mem_fd)
        except:
            pass

# ==========================================
# 🔍 ฟังก์ชันค้นหาข้อมูลพื้นฐานของเกม
# ==========================================
def get_game_pid():
    try:
        pid_str = subprocess.check_output(["pgrep", "aces"]).decode().strip().split('\n')[0]
        return int(pid_str)
    except subprocess.CalledProcessError:
        print("[-] Error: หาโปรเซส 'aces' (War Thunder) ไม่เจอ! เปิดเกมหรือยัง?")
        sys.exit(1)

def get_game_base_address(pid):
    try:
        with open(f"/proc/{pid}/maps", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 6 and parts[5].endswith("aces"): 
                    base_str = parts[0].split("-")[0]
                    return int(base_str, 16)
    except Exception as e:
        print(f"[-] Error reading maps: {e}")
    return 0

# ==========================================
# 🚀 ระบบสั่งการหลัก (Main Execution)
# ==========================================
def main():
    print("[*] กำลังเตรียมระบบ Matrix Radar และ W2S...")
    
    # 1. หา PID และ Base Address
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    
    if base_address == 0:
        print("[-] Error: หา Base Address ของเกมไม่เจอ")
        sys.exit(1)
        
    print(f"[+] เจอ War Thunder (PID: {pid})")
    print(f"[+] Base Address ของ aces : {hex(base_address)}")
    
    # 2. 🚨 สร้าง Memory Scanner ตรงนี้! (ต้องสร้างก่อนเอาไปใช้งาน)
    try:
        scanner = MemoryScanner(pid)
    except PermissionError:
        print("[-] Error: สิทธิ์ไม่พอ! อย่าลืมรันด้วย sudo นะครับ")
        sys.exit(1)
        
    print("[*] กำลังเชื่อมต่อกับ CGame...\n")
    time.sleep(1)
    
    # 3. วนลูปอ่านค่าดึง View Matrix แบบ Live สด
    try:
        while True:
            os.system('clear')
            print("🎯 [War Thunder - Matrix & W2S Radar]")
            print("-" * 60)
            
            cgame_base = get_cgame_base(scanner, base_address)
            
            if cgame_base != 0:
                print(f"✅ CGame Base ของจริง: {hex(cgame_base)}")
                view_matrix = get_view_matrix(scanner, cgame_base)
                
                if view_matrix:
                    # -----------------------------------------------------
                    # 🧮 ทดสอบระบบ World-To-Screen (W2S) ทันทีที่ได้ Matrix!
                    # -----------------------------------------------------
                    enemy_x, enemy_y, enemy_z = 1680.0, -130.0, 5.0
                    screen_pos = world_to_screen(view_matrix, enemy_x, enemy_y, enemy_z, screen_w, screen_h)
                    
                    print("\n[จำลองพิกัดศัตรู: X=1680, Y=-130, Z=5]")
                    if screen_pos:
                        print(f"🎯 แปลงพิกัดสำเร็จ! วาดกรอบศัตรูที่หน้าจอ: [ X: {screen_pos[0]} , Y: {screen_pos[1]} ]")
                    else:
                        print("👀 ศัตรูเป้าหมายอยู่ข้างหลังเรา (หรือหลบอยู่หลังกล้อง)")
                    print("-" * 60)
                else:
                    print("❌ ไม่สามารถดึง View Matrix ได้")
            else:
                print("❌ ไม่สามารถดึง CGame Base ได้")
                
            print("[*] ขยับเมาส์หันมุมกล้องในเกมดูว่าพิกัด X, Y บนจอเปลี่ยนตามไหม (กด Ctrl+C เพื่อหยุด)")
            
            time.sleep(0.05) # อัปเดต 20 ครั้งต่อวินาที เพื่อความลื่นไหล
            
    except KeyboardInterrupt:
        print("\n[!] ปิดระบบเรียบร้อยแล้ว")

if __name__ == "__main__":
    main()