import sys
import time
import struct
import math
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont

# นำเข้าเครื่องมือสแกนเนอร์และสูตรคำนวณจากไฟล์ของคุณ
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import (
    get_cgame_base, get_view_matrix, world_to_screen, get_unit_pos, 
    get_all_units, get_unit_3d_box_data, calculate_3d_box_corners, get_weapon_barrel
)

# 🎯 ตั้งค่าหน้าจอ (แก้ให้ตรงกับจอคุณ)
SCREEN_WIDTH = 2560
SCREEN_HEIGHT = 1440

class ESPOverlay(QWidget):
    def __init__(self, scanner, base_address):
        super().__init__()
        self.scanner = scanner
        self.base_address = base_address
        self.frame_count = 0 
        
        # ตัวแปรสำหรับทำ Python Cheat Engine
        self.last_cw_data = {} # เปลี่ยนเป็น Dict เพื่อเก็บของหลายคัน
        
        # --- 🪄 เวทมนตร์สร้างหน้าต่างล่องหน ---
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setGeometry(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(16) # ~60 FPS

    def live_offset_scanner(self, u_ptr):
        """ เครื่องสแกนหา Offset อัตโนมัติ (เป้าหมายจาก Windows Dump: 0xE00, 0xE78, 0xEA8) """
        
        # 1. วิ่งหา Pointer ของ Turret/Weapon จาก Offset ตัวเต็ง
        target_offsets = [0xE00, 0xE78, 0xEA8, 0xEA0]
        wpn_ptr = 0
        used_base = 0
        
        for off in target_offsets:
            raw_ptr = self.scanner.read_mem(u_ptr + off, 8)
            if raw_ptr:
                val = struct.unpack("<Q", raw_ptr)[0]
                if val > 0x10000000000: # กรองเฉพาะ Pointer จริง
                    wpn_ptr = val
                    used_base = off
                    break
                    
        if wpn_ptr == 0: return

        print("\n" + "="*60)
        print(f"🔍 [LIVE SCANNER] เจาะคลังแสงที่ Offset: {hex(used_base)} (Pointer: {hex(wpn_ptr)})")
        print("🎯 ขยับเมาส์ (หันป้อมปืน) ไปมาเรื่อยๆ เพื่อหาองศา!")

        # อ่านข้อมูลก้อนใหญ่มาวิเคราะห์ (ขนาด 1 KB)
        data = self.scanner.read_mem(wpn_ptr, 0x400)
        if not data: return

        # ---------------------------------------------------------
        # ภารกิจที่ 1: หาองศา Yaw/Pitch (ดักจับความเคลื่อนไหว)
        # ---------------------------------------------------------
        # สแกนหา Array ที่มีขนาด 1-10 ชิ้น (เข้าข่าย ControllableWeapon)
        for arr_off in range(0x50, 0x3F0, 8):
            arr_ptr = struct.unpack_from("<Q", data, arr_off)[0]
            count = struct.unpack_from("<I", data, arr_off + 8)[0]
            
            if arr_ptr > 0x10000000000 and 0 < count <= 10:
                cw_data = self.scanner.read_mem(arr_ptr, 0x150)
                if cw_data:
                    cache_key = f"{used_base}_{arr_off}"
                    if cache_key in self.last_cw_data:
                        found_moving = False
                        for i in range(0, 0x140, 4):
                            val_now = struct.unpack_from("<f", cw_data, i)[0]
                            val_old = struct.unpack_from("<f", self.last_cw_data[cache_key], i)[0]
                            
                            # กรอง: ขยับเกิน 0.005 และค่าอยู่ในช่วงของเรเดียน (-3.15 ถึง 3.15)
                            if abs(val_now - val_old) > 0.005 and -3.15 <= val_now <= 3.15:
                                print(f"  👉 [องศาปืน!] Array {hex(arr_off)} | Offset ในปืน {hex(i):<5} | ขยับ: {val_now:.3f}")
                                found_moving = True
                    
                    self.last_cw_data[cache_key] = cw_data

        # ---------------------------------------------------------
        # ภารกิจที่ 2: หาพิกัดจุดหมุน (X,Y,Z ที่อยู่นิ่งๆ)
        # ---------------------------------------------------------
        for arr_off in range(0x50, 0x3F0, 8):
            arr_ptr = struct.unpack_from("<Q", data, arr_off)[0]
            count = struct.unpack_from("<I", data, arr_off + 8)[0]
            
            if arr_ptr > 0x10000000000 and 0 < count <= 10:
                # ลองทะลวงเข้าไปอีก 1 ชั้น (เพราะ PositionInfo มักจะซ้อน Pointer)
                ptr_data = self.scanner.read_mem(arr_ptr, 8)
                if ptr_data:
                    inner_ptr = struct.unpack("<Q", ptr_data)[0]
                    if inner_ptr > 0x10000000000:
                        i_data = self.scanner.read_mem(inner_ptr, 0x150)
                        if i_data:
                            for i in range(0, 0x130, 4):
                                x, y, z = struct.unpack_from("<fff", i_data, i)
                                # กรอง: จุดหมุนมักจะไม่เกิน 10 เมตรจากตัวรถ และไม่ใช่ 0 ล้วน
                                if (-10.0 < x < 10.0) and (-10.0 < y < 10.0) and (-10.0 < z < 10.0):
                                    if abs(x) > 0.01 or abs(y) > 0.01 or abs(z) > 0.01:
                                        print(f"  📦 [พิกัดจุดหมุน] Array {hex(arr_off)} | Offset {hex(i):<5} : [X:{x:.2f}, Y:{y:.2f}, Z:{z:.2f}]")
        print("="*60)

    def paintEvent(self, event):
        self.frame_count += 1
        # ปริ้นสแกนเนอร์ทุกๆ 30 เฟรม (ครึ่งวินาที)
        should_log = (self.frame_count % 30 == 0)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setFont(QFont("Arial", 14, QFont.Bold))
        painter.setPen(QColor(0, 255, 0, 255))
        painter.drawText(20, 30, "🟢 ESP Overlay: Live Turret Scanner Active!")

        cgame_base = get_cgame_base(self.scanner, self.base_address)
        if cgame_base == 0: return
            
        view_matrix = get_view_matrix(self.scanner, cgame_base)
        if not view_matrix: return

        all_units = get_all_units(self.scanner, cgame_base)
        
        for idx, u_ptr in enumerate(all_units):
            
            # --- 🚨 ยิงระบบสแกนรถถังคันแรก ---
            if should_log and idx == 0: 
                self.live_offset_scanner(u_ptr)
            # ---------------------------------

            # วาดกล่อง 3D Box (ทำงานคู่กันไป)
            box_data = get_unit_3d_box_data(self.scanner, u_ptr)
            if not box_data: continue
            pos, bmin, bmax, R = box_data

            corners_3d = calculate_3d_box_corners(pos, bmin, bmax, R)
            pts = []
            all_valid = True
            
            for c in corners_3d:
                res = world_to_screen(view_matrix, c[0], c[1], c[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                if res and res[2] >= 0.001:
                    pts.append((res[0], res[1]))
                else:
                    all_valid = False
                    break
                    
            if not all_valid or len(pts) != 8:
                continue
                
            painter.setPen(QPen(QColor(255, 0, 0, 255), 2))
            edges = [
                (0,1), (1,2), (2,3), (3,0), 
                (4,5), (5,6), (6,7), (7,4), 
                (0,4), (1,5), (2,6), (3,7)  
            ]
            for e1, e2 in edges:
                painter.drawLine(int(pts[e1][0]), int(pts[e1][1]), int(pts[e2][0]), int(pts[e2][1]))


if __name__ == '__main__':
    print("[*] กำลังเปิดระบบ ESP Overlay พร้อม Python Live Scanner...")
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    
    try:
        scanner = MemoryScanner(pid)
    except PermissionError:
        print("[-] สิทธิ์ไม่พอ! รันด้วย sudo นะครับ")
        sys.exit(1)

    app = QApplication(sys.argv)
    overlay = ESPOverlay(scanner, base_addr)
    overlay.show()
    sys.exit(app.exec_())