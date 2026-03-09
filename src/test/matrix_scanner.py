import struct
import subprocess
import time
import os

def get_pid():
    try:
        return int(subprocess.check_output(["pgrep", "aces"]).decode().strip().split('\n')[0])
    except: return None

def main():
    pid = get_pid()
    if not pid: return print("❌ เปิดเกมก่อน!")
    
    # ดึง Base Address
    base_addr = 0
    with open(f"/proc/{pid}/maps", "r") as f:
        for line in f:
            if "aces" in line:
                base_addr = int(line.split("-")[0], 16)
                break
                
    # 🎯 พิกัดทองคำที่เราได้จาก Ghidra
    targets = {
        "DAT_0939e040": base_addr + 0x8f9e040,
        "DAT_0939e070": base_addr + 0x8f9e070,
        "ZONE_0939e000": base_addr + 0x8f9e000 # ดักดูทั้งโซนเผื่อมันเขียนเรียงกัน
    }

    print(f"[*] Base: {hex(base_addr)}")
    
    try:
        with open(f"/proc/{pid}/mem", "rb", 0) as mem_f:
            while True:
                os.system('clear')
                print("[*] 📡 กำลังเฝ้าดู Global Camera Address... **ขยับเมาส์รัวๆ!**\n")
                
                for name, addr in targets.items():
                    mem_f.seek(addr)
                    # อ่านมา 16 floats (64 bytes)
                    data = mem_f.read(64)
                    if len(data) == 64:
                        m = struct.unpack("<16f", data)
                        print(f"--- {name} ({hex(addr)}) ---")
                        print(f"R1: {m[0]:.2f}, {m[1]:.2f}, {m[2]:.2f}, {m[3]:.2f}")
                        print(f"R2: {m[4]:.2f}, {m[5]:.2f}, {m[6]:.2f}, {m[7]:.2f}")
                        print(f"R3: {m[8]:.2f}, {m[9]:.2f}, {m[10]:.2f}, {m[11]:.2f}")
                        print(f"R4: {m[12]:.2f}, {m[13]:.2f}, {m[14]:.2f}, {m[15]:.2f}\n")
                
                time.sleep(0.1)
    except KeyboardInterrupt: pass

if __name__ == "__main__":
    main()