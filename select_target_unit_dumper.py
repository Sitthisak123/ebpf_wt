import os
import sys
import struct
import math
import threading
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont

from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import (
    get_cgame_base, get_view_matrix, world_to_screen,
    get_all_units, get_unit_3d_box_data, calculate_3d_box_corners
)

SCREEN_WIDTH = 2560
SCREEN_HEIGHT = 1440

# ==========================================
# 🧠 Shared State สำหรับคุยกันระหว่าง Console และ Overlay
# ==========================================
class DumperState:
    units = []
    selected_idx = 0
    selected_ptr = 0
    my_unit = 0
    cgame_base = 0

def hex_dump(data, start_address):
    """ฟังก์ชันจัดหน้าตา Memory ให้ดูง่ายเหมือน Cheat Engine"""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_str = ' '.join(f"{b:02X}" for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        lines.append(f"0x{start_address+i:03X} | {hex_str:<47} | {ascii_str}")
    return '\n'.join(lines)

# ==========================================
# 🖌️ GUI Overlay สำหรับวาดกล่อง 2D Box เป้าหมายที่เลือก
# ==========================================
class DumperOverlay(QWidget):
    def __init__(self, scanner):
        super().__init__()
        self.scanner = scanner
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setGeometry(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(16)

    def paintEvent(self, event):
        painter = QPainter()
        painter.begin(self) 
        painter.setRenderHint(QPainter.Antialiasing)
        
        try:
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            painter.setPen(QColor(255, 0, 255, 255))
            painter.drawText(20, 40, f"🔎 X-RAY DUMPER ACTIVE | Current Target: {hex(DumperState.selected_ptr)}")

            if not DumperState.selected_ptr or not DumperState.cgame_base: return
            
            view_matrix = get_view_matrix(self.scanner, DumperState.cgame_base)
            if not view_matrix: return

            # ดึงข้อมูล Box ของเป้าหมายที่เราเลือกใน Console
            box_data = get_unit_3d_box_data(self.scanner, DumperState.selected_ptr)
            if not box_data: return

            pos, bmin, bmax, R = box_data
            corners_3d = calculate_3d_box_corners(pos, bmin, bmax, R)
            
            pts = []
            for c in corners_3d:
                res = world_to_screen(view_matrix, c[0], c[1], c[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                if res and res[2] >= 0.001:
                    pts.append((res[0], res[1]))
            
            if len(pts) == 8:
                # 🧮 แปลง 3D Box เป็น 2D Box (หาค่า min/max ของแกน x และ y หน้าจอ)
                min_x = min([p[0] for p in pts])
                max_x = max([p[0] for p in pts])
                min_y = min([p[1] for p in pts])
                max_y = max([p[1] for p in pts])
                
                width = max_x - min_x
                height = max_y - min_y
                
                # วาดกล่อง 2D Box สีชมพู (Magenta)
                painter.setPen(QPen(QColor(255, 0, 255, 255), 3))
                painter.drawRect(int(min_x), int(min_y), int(width), int(height))
                
                # ลากเส้น Snapline (จากกลางจอล่าง ชี้ไปที่เป้าหมาย จะได้หาเป้าเจอเร็วๆ)
                painter.setPen(QPen(QColor(255, 0, 255, 150), 1))
                painter.drawLine(SCREEN_WIDTH // 2, SCREEN_HEIGHT, int(min_x + width/2), int(max_y))
                
        except Exception:
            pass
        finally:
            painter.end()

# ==========================================
# ⌨️ Console Thread สำหรับรับคำสั่งโดยไม่ให้ UI ค้าง
# ==========================================
def console_controller(scanner, base_addr):
    cgame_base = get_cgame_base(scanner, base_addr)
    if not cgame_base:
        print("[-] รอเข้าเกม หรือหา CGame ไม่เจอ...")
        return
        
    DumperState.cgame_base = cgame_base
    control_addr = base_addr + (0x09394248 - 0x400000)
    my_unit_raw = scanner.read_mem(control_addr, 8)
    DumperState.my_unit = struct.unpack("<Q", my_unit_raw)[0] if my_unit_raw else 0

    DumperState.units = get_all_units(scanner, cgame_base)
    if DumperState.units: DumperState.selected_ptr = DumperState.units[0]

    while True:
        os.system('clear')
        if not DumperState.units:
            print("[-] ไม่พบ Unit ในแผนที่... พิมพ์ R เพื่อรีเฟรช")
        else:
            u_ptr = DumperState.units[DumperState.selected_idx]
            DumperState.selected_ptr = u_ptr
            
            marker = "🟢 [รถถังของคุณ (MY UNIT)]" if u_ptr == DumperState.my_unit else "🔴 [เป้าหมายอื่น (TARGET)]"
            
            preview_team = struct.unpack("<B", scanner.read_mem(u_ptr + 0xDF0, 1) or b'\x00')[0]
            preview_state = struct.unpack("<H", scanner.read_mem(u_ptr + 0xD68, 2) or b'\x00\x00')[0]

            print("="*60)
            print(f"🎯 เป้าหมายที่: {DumperState.selected_idx+1} / {len(DumperState.units)}")
            print(f"📌 Address: {hex(u_ptr)} {marker}")
            print(f"🔎 ข้อมูลเบื้องต้น -> Team (0xDF0): {preview_team} | State (0xD68): {preview_state}")
            print("="*60)
            print("\n[👁️ ดูหน้าจอเกม จะมีกรอบ 2D Box และเส้นสีชมพูชี้เป้าหมายนี้อยู่]")
            
        print("\nแผงควบคุม:")
        print(" [N] - ⏭️ เลื่อนไปเป้าหมายถัดไป (Next)")
        print(" [P] - ⏮️ ย้อนกลับเป้าหมายก่อนหน้า (Prev)")
        print(" [L] - 💾 DUMP LOG (ดู Memory เป้าหมายนี้)")
        print(" [R] - 🔄 โหลดเป้าหมายใหม่ (Refresh)")
        print(" [Q] - ❌ ออกจากโปรแกรม (Quit)")
        
        cmd = input("\n>>> เลือกคำสั่ง: ").strip().upper()
        
        if not DumperState.units and cmd not in ['R', 'Q']: continue
            
        if cmd == 'N':
            DumperState.selected_idx = (DumperState.selected_idx + 1) % len(DumperState.units)
        elif cmd == 'P':
            DumperState.selected_idx = (DumperState.selected_idx - 1) % len(DumperState.units)
        elif cmd == 'R':
            DumperState.units = get_all_units(scanner, DumperState.cgame_base)
            DumperState.selected_idx = 0
        elif cmd == 'Q':
            os._exit(0) # บังคับปิดทุก Thread
        elif cmd == 'L':
            os.system('clear')
            print(f"--- 💾 MEMORY DUMP ของ Address: {hex(DumperState.selected_ptr)} ---")
            
            print("\n[1] โซนสถานะรถถังและทีม (0xD00 - 0xE00):")
            data = scanner.read_mem(DumperState.selected_ptr + 0xD00, 0x100)
            if data: print(hex_dump(data, 0xD00))
            
            print("\n[2] โซนค้นหา UnitInfo (0xD18, 0xD20, 0xDF8, 0xE00):")
            for off in [0xD18, 0xD20, 0xDF8, 0xE00]:
                raw = scanner.read_mem(DumperState.selected_ptr + off, 8)
                if raw:
                    ptr = struct.unpack("<Q", raw)[0]
                    if 0x10000 < ptr < 0x7FFFFFFFFFFF:
                        print(f"  ✅ เจอ Pointer (น่าจะ UnitInfo) ที่ Offset: {hex(off)} -> ชี้ไปที่ {hex(ptr)}")
                        
                        fam_data = scanner.read_mem(ptr + 0x12A0, 0x40)
                        if fam_data:
                            print(f"     [+] Dump บริเวณ Unit Family (0x12A0 - 0x12E0):")
                            print(hex_dump(fam_data, 0x12A0))
                            
                        name_p_raw = scanner.read_mem(ptr + 0x28, 8)
                        if name_p_raw:
                            name_p = struct.unpack("<Q", name_p_raw)[0]
                            if 0x10000 < name_p < 0x7FFFFFFFFFFF:
                                n_data = scanner.read_mem(name_p, 32)
                                if n_data:
                                    try:
                                        print(f"     [+] ชื่อเป้าหมาย: {n_data.split(b'\\x00')[0].decode('utf-8', errors='ignore')}")
                                    except: pass
            input("\n>>> กด Enter เพื่อกลับไปหน้าควบคุม...")

# ==========================================
# 🚀 จุดสตาร์ทโปรแกรม
# ==========================================
def main():
    print("[*] 🚀 กำลังโหลด THE INTERACTIVE MEMORY SCANNER (OVERLAY MODE)...")
    try:
        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        scanner = MemoryScanner(pid)
    except Exception as e:
        print(f"[-] Error: {e}")
        sys.exit(1)

    # สร้าง Thread 분صلสำหรับ Console (เพื่อไม่ให้ GUI ค้าง)
    cli_thread = threading.Thread(target=console_controller, args=(scanner, base_addr), daemon=True)
    cli_thread.start()

    # เริ่มระบบ GUI วาดภาพบนจอหลัก
    app = QApplication(sys.argv)
    overlay = DumperOverlay(scanner)
    overlay.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()