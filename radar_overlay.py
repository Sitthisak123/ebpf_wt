import sys
import time
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
        self.frame_count = 0  # ตัวนับเฟรมสำหรับทำ Smart Logger
        
        # --- 🪄 เวทมนตร์สร้างหน้าต่างล่องหน ---
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setGeometry(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(16) # ~60 FPS

    def paintEvent(self, event):
        self.frame_count += 1
        # ให้มัน Print Log ลง Terminal แค่ 1 ครั้ง ทุกๆ 60 เฟรม (1 วินาที)
        should_log = (self.frame_count % 60 == 0)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # ---------------------------------------------------------
        # 1. ทดสอบวาดตัวหนังสือลงจอก่อนเลย (เช็คว่า PyQt5 ทำงานไหม)
        # ---------------------------------------------------------
        painter.setFont(QFont("Arial", 14, QFont.Bold))
        painter.setPen(QColor(0, 255, 0, 255)) # สีเขียว
        painter.drawText(20, 30, "🟢 ESP Overlay is Running!")

        # ---------------------------------------------------------
        # 2. ดึงข้อมูลหลัก (CGame & View Matrix)
        # ---------------------------------------------------------
        cgame_base = get_cgame_base(self.scanner, self.base_address)
        if cgame_base == 0: 
            if should_log: print("[-] Log: CGame Base เป็น 0 (หาไม่เจอ)")
            return
            
        view_matrix = get_view_matrix(self.scanner, cgame_base)
        if not view_matrix: 
            if should_log: print("[-] Log: อ่าน View Matrix ไม่ได้")
            return

        # ---------------------------------------------------------
        # 3. ดึงรายชื่อรถถัง
        # ---------------------------------------------------------
        all_units = get_all_units(self.scanner, cgame_base)
        
        valid_pos_count = 0
        drawn_count = 0
        
        # ตั้งค่าปากกาสีแดงสำหรับวาดกรอบ
        painter.setPen(QPen(QColor(255, 0, 0, 255), 2))
        
        all_units = get_all_units(self.scanner, cgame_base)
        has_logged_this_frame = False # ตัวดักไม่ให้ Log สแปมรัวๆ
        
        for u_ptr in all_units:
            box_data = get_unit_3d_box_data(self.scanner, u_ptr)
            if not box_data: continue
            
            pos, bmin, bmax, R = box_data

            # อนุญาตให้ปริ้น Log ได้ ถ้าครบ 1 วินาที และเฟรมนี้ยังไม่ได้ปริ้นอะไรเลย
            is_logging_target = should_log and not has_logged_this_frame

            # -----------------------------------------------------
            # 🔫 วาด Laser ปืน (Barrel ESP) - สีเขียว (Green)
            # -----------------------------------------------------
            try:
                barrel_data = get_weapon_barrel(self.scanner, u_ptr, pos, R, should_log=is_logging_target)
                
                if barrel_data:
                    if is_logging_target:
                        # ถ้าคันนี้มีปืน ให้ล็อคไว้เลย คันต่อไปในวินาทีนี้จะได้ไม่แย่งปริ้น
                        has_logged_this_frame = True 
                        
                    pivot_3d, tip_3d = barrel_data
                    res_p = world_to_screen(view_matrix, pivot_3d[0], pivot_3d[1], pivot_3d[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    res_t = world_to_screen(view_matrix, tip_3d[0], tip_3d[1], tip_3d[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                    
                    if res_p and res_t and res_p[2] > 0 and res_t[2] > 0:
                        painter.setPen(QPen(QColor(0, 255, 0, 255), 3)) 
                        painter.drawLine(int(res_p[0]), int(res_p[1]), int(res_t[0]), int(res_t[1]))
            except Exception as e:
                pass

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
                
            # แถม: Snapline ลากไปที่จุดกึ่งกลางของฐาน (จุด 0 กับ 2 ครอสกัน)
            base_center_x = (pts[0][0] + pts[2][0]) / 2
            base_center_y = (pts[0][1] + pts[2][1]) / 2
            painter.setPen(QPen(QColor(255, 0, 0, 150), 1))
            painter.drawLine(SCREEN_WIDTH // 2, SCREEN_HEIGHT, int(base_center_x), int(base_center_y))

if __name__ == '__main__':
    print("[*] กำลังเปิดระบบ ESP Overlay พร้อม Smart Logger...")
    
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
    
    print("[+] หน้าต่าง Overlay เปิดแล้ว! สังเกต Log ด้านล่างนี้:")
    sys.exit(app.exec_())