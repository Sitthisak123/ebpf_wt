import os
import sys
import struct
import math
import time
from main import MemoryScanner, get_game_pid, get_game_base_address

def main():
    pid = get_game_pid()
    scanner = MemoryScanner(pid)
    
    # รายการ Address ที่คุณต้องการตรวจสอบ
    target_addresses = [
        0x95bbda4, 0x95bbd44, 0x95bbce4, 0x95bbc84, 0x95bbc24, 0x95bbbc4,
        0x75144c066370, 0x75144c058b88, 0x75144c04aec8, 0x75144c04aec4, 0x75144c04aec0,
        0x75142c963a64, 0x75142c9639f0, 0x75142c32ac50, 0x75140f4058f0,
        0x75134df8eba0, 0x75134df8e984, 0x75134c8512a8,
        0x4138ae3c, 0x413892f0, 0x41384ae8, 0x41383590,
        0x3e9d01d8, 0x3e9d0164, 0x3e1caa98, 0x2932329c
    ]

    os.system("clear")
    print("=========================================================================================")
    print(" 🚀 VELOCITY HUNTER - Monitoring Specific Addresses")
    print("=========================================================================================")
    print(f"{"ADDRESS":<16} | {"X / VAL":>10} | {"Y":>10} | {"Z":>10} | {"SPEED (KM/H)":>12}")
    print("-" * 90)

    while True:
        output_lines = []
        for addr in target_addresses:
            # อ่านข้อมูล 12 byte (สำหรับ x, y, z float)
            data = scanner.read_mem(addr, 12)
            if data and len(data) >= 4:
                try:
                    # ลองอ่านเป็น Float 3 ตัว (Vector)
                    v = struct.unpack("<fff", data)
                    vx, vy, vz = v
                    
                    # คำนวณความเร็ว (Magnitude)
                    # ถ้าเป็นความเร็วปกติ เลขควรจะอยู่ในช่วงที่สมเหตุสมผล
                    speed = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                    
                    # ถ้าค่า Speed สูงเกินไป หรือไม่ใช่เลขปกติ (NaN) อาจจะเป็นข้อมูลประเภทอื่น
                    if not math.isfinite(speed) or speed > 5000:
                        # แสดงแค่ค่าแรกตัวเดียว
                        v1 = struct.unpack("<f", data[:4])[0]
                        line = f"{hex(addr):<16} | {v1:>10.4f} | {"-":>10} | {"-":>10} | {"Data?":>12}"
                    else:
                        line = f"{hex(addr):<16} | {vx:>10.2f} | {vy:>10.2f} | {vz:>10.2f} | {speed:>12.2f}"
                    
                    output_lines.append(line)
                except:
                    output_lines.append(f"{hex(addr):<16} | {"ERROR":>10} | {"-":>10} | {"-":>10} | {"-":>12}")
            else:
                output_lines.append(f"{hex(addr):<16} | {"INVALID":>10} | {"-":>10} | {"-":>10} | {"-":>12}")

        # อัปเดตหน้าจอ
        sys.stdout.write("\033[H") # เลื่อนเคอร์เซอร์ไปบนสุด
        print("=========================================================================================")
        print(" 🚀 VELOCITY HUNTER - Monitoring Specific Addresses")
        print("=========================================================================================")
        print(f"{"ADDRESS":<16} | {"X / VAL":>10} | {"Y":>10} | {"Z":>10} | {"SPEED (KM/H)":>12}")
        print("-" * 90)
        for l in output_lines:
            print(l)
        
        time.sleep(0.1)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: sys.exit(0)
