import os
import sys
import math
import time
import struct
import subprocess
# 🎯 ตั้งค่าหน้าจอของคุณ
screen_w = 2560
screen_h = 1440

# 🚨 ดึง (Import) ฟังก์ชันทั้งหมด รวมถึง world_to_screen ด้วย!
try:
    from src.utils.mul import get_cgame_base, get_view_matrix, get_unit_pos, world_to_screen
    import src.utils.validator
except ImportError:
    print("[-] Error: หาไฟล์ src/utils/* ไม่เจอ")
    sys.exit(1)

# ==========================================
# 🛠️ คลาสสำหรับอ่าน Memory (ทำหน้าที่เป็น Scanner)
# ==========================================
class MemoryScanner:
    def __init__(self, pid):
        self.pid = pid
        self.mem_fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)

    def read_mem(self, address, size):
        # 🛡️ Pointer Validation: ป้องกันการอ่าน Address ที่เป็น 0 หรือค่าน้อยผิดปกติ
        # Memory ใน Linux ของแอป 64-bit มักจะเริ่มต้นที่ตำแหน่งสูงกว่า 0x10000 เสมอ
        if address is None or address <= 0x10000:
            return None
            
        try:
            os.lseek(self.mem_fd, address, os.SEEK_SET)
            return os.read(self.mem_fd, size)
        except OSError:
            # 🔇 ปิดการทำงานของ print เพื่อไม่ให้มันสแปมหน้าจอเวลาที่อ่านพลาด (Errno 5)
            # เพราะในเกมมีการเกิด/ตายของ Object ตลอดเวลา การอ่านพลาดเป็นเรื่องปกติ
            return None
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
    scanner = MemoryScanner(pid)
    validator = src.utils.validator.OffsetValidator(scanner, base_address)
    if not validator.run_diagnostics():
        print("🚨 [CRITICAL] Offsets ไม่ถูกต้อง! กรุณาตรวจสอบ Ghidra หรืออัปเดตเลข DAT_MANAGER")
        # sys.exit(1) # ปิดโปรแกรมหากพิกัดเพี้ยน

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
def auto_find_unit_position(scanner, u_ptr):
    if u_ptr == 0: return
    
    # ดึงข้อมูลรวดเดียวตั้งแต่ Offset 0xB00 ถึง 0xE00 (ช่วงที่พิกัดน่าจะอยู่)
    data = scanner.read_mem(u_ptr + 0xB00, 0x300)
    if not data: return
    
    print(f"\n🔍 [สแกนยูนิต: {hex(u_ptr)}] กำลังหาพิกัด X, Y, Z...")
    
    # สแกนทีละ 4 bytes เพื่อหา Float 3 ตัวติดกัน
    for i in range(0, len(data) - 12, 4):
        x, y, z = struct.unpack_from("<fff", data, i)
        
        # เงื่อนไขพิกัดใน War Thunder:
        # 1. ต้องเป็นตัวเลขจริง (ไม่ใช่ NaN / Inf)
        # 2. ต้องไม่ใช่ 0.0 ทั้งหมด
        # 3. พิกัดแผนที่มักจะไม่เกิน 20,000 เมตร และความสูง (Y) ไม่เกิน 5,000
        if math.isfinite(x) and math.isfinite(y) and math.isfinite(z):
            if x != 0.0 and y != 0.0 and z != 0.0:
                if abs(x) < 20000 and abs(y) < 5000 and abs(z) < 20000:
                    # ถ้าผ่านเงื่อนไข ให้พิมพ์ Offset นั้นออกมา!
                    real_offset = 0xB00 + i
                    print(f"✨ เจอพิกัดที่น่าจะใช่! -> Offset: [ {hex(real_offset)} ] | X:{x:.1f} Y:{y:.1f} Z:{z:.1f}")


if __name__ == "__main__":
    main()