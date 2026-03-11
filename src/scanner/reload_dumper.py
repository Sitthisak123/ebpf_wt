import os
import sys
import time
import struct
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base, get_all_units

def hex_float_dump(data, start_address):
    """ฟังก์ชัน Dump Memory ที่แปลงค่าเป็นตัวเลข Float ให้ดูง่ายๆ"""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_str = ' '.join(f"{b:02X}" for b in chunk)
        
        # แปลง 4 bytes เป็น Float
        floats = []
        for j in range(0, len(chunk), 4):
            if len(chunk) - j >= 4:
                try:
                    f_val = struct.unpack("<f", chunk[j:j+4])[0]
                    # กรองค่า Float ขยะทิ้ง (เอาเฉพาะค่า -1000 ถึง 1000)
                    if -1000.0 < f_val < 1000.0:
                        floats.append(f"{f_val:8.3f}")
                    else:
                        floats.append("  ------")
                except:
                    floats.append("  ------")
            else:
                floats.append("        ")
                
        float_str = ' | '.join(floats)
        lines.append(f"{hex(start_address+i)} | {hex_str:<47} | Float: [ {float_str} ]")
    return '\n'.join(lines)

def main():
    print("[*] 🚀 กำลังโหลด THE RELOAD PROGRESS SCANNER...")
    try:
        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        scanner = MemoryScanner(pid)
    except Exception as e:
        print(f"[-] Error: {e}")
        sys.exit(1)
        
    cgame_base = get_cgame_base(scanner, base_addr)
    if not cgame_base:
        print("[-] หา CGame ไม่เจอ...")
        return
        
    units = get_all_units(scanner, cgame_base)
    if not units:
        print("[-] ไม่พบเป้าหมายในแมพ...")
        return

    # หาตัวเราเอง
    control_addr = base_addr + (0x09394248 - 0x400000)
    my_unit_raw = scanner.read_mem(control_addr, 8)
    my_unit = struct.unpack("<Q", my_unit_raw)[0] if my_unit_raw else 0

    idx = 0
    while True:
        os.system('clear')
        if not units: break
        u_ptr = units[idx]
        
        marker = "🟢 [นี่คือรถถังของคุณ (TEST WITH THIS!)]" if u_ptr == my_unit else "🔴 [เป้าหมายอื่น]"
        
        # ลองดึงค่า 0x8F0 แบบ Float มาโชว์
        test_val = 0.0
        raw_val = scanner.read_mem(u_ptr + 0x8F0, 4)
        if raw_val:
            try:
                test_val = struct.unpack("<f", raw_val)[0]
            except: pass

        print("="*70)
        print(f"🎯 เป้าหมายที่: {idx+1} / {len(units)}")
        print(f"📌 Address: {hex(u_ptr)} {marker}")
        print(f"🔎 ค่าที่ 0x8F0 ตอนนี้: {test_val:.4f}")
        print("="*70)
        print("\nแผงควบคุม:")
        print(" [N] - ⏭️ เลื่อนไปเป้าหมายถัดไป (แนะนำให้เลื่อนหาตัวคุณเอง 🟢)")
        print(" [M] - 👁️ MONITOR โหมดดูค่า 0x8F0 แบบ Real-time (ลองกดแล้วไปยิงปืนในเกม)")
        print(" [L] - 💾 DUMP FLOAT (ดู Memory ช่วง 0x8A0 - 0x920 เพื่อหา Reload แบบสดๆ)")
        print(" [Q] - ❌ ออกจากโปรแกรม")
        
        cmd = input("\n>>> เลือกคำสั่ง: ").strip().upper()
        
        if cmd == 'N':
            idx = (idx + 1) % len(units)
        elif cmd == 'Q':
            break
        elif cmd == 'M':
            print("\n[*] 👁️ เริ่มมอนิเตอร์ค่า 0x8F0... (สลับไปยิงปืนในเกมได้เลย กด Ctrl+C เพื่อหยุด)")
            try:
                while True:
                    r_raw = scanner.read_mem(u_ptr + 0x8F0, 4)
                    if r_raw:
                        v = struct.unpack("<f", r_raw)[0]
                        bar = "█" * int(v * 20)
                        sys.stdout.write(f"\r[0x8F0] ค่า Float: {v:7.4f} | หลอด: {bar:<20}")
                        sys.stdout.flush()
                    time.sleep(0.05)
            except KeyboardInterrupt:
                pass
        elif cmd == 'L':
            os.system('clear')
            print(f"--- 💾 FLOAT DUMP ของ Address: {hex(u_ptr)} ---")
            print("[*] สังเกตหาตัวเลข Float ที่มีค่า 1.000 (พร้อมยิง) พอคุณยิงปืนมันจะตกไปที่ 0.000")
            print("[*] แนะนำให้จำตัวเลขที่หน้าตาคล้าย 1.000 ไว้ แล้วกลับไปยิงปืน แล้วกลับมากด DUMP ใหม่\n")
            
            # โซนเป้าหมายที่คาดว่าจะมี Reload (0x8A0 ถึง 0x930)
            data = scanner.read_mem(u_ptr + 0x8A0, 0x90)
            if data: 
                print(hex_float_dump(data, 0x8A0))
                
            input("\n>>> กด Enter เพื่อกลับไปหน้าควบคุม...")

if __name__ == '__main__':
    main()