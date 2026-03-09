import sys
import time
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont

# นำเข้าเครื่องมือสแกนเนอร์และสูตรคำนวณจากไฟล์ของคุณ
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base, get_view_matrix, world_to_screen, get_unit_pos, get_all_units, get_unit_3d_box_data, calculate_3d_box_corners

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

        for u_ptr in all_units:
            # 1. ดึงข้อมูล 3D (องศา, ขนาด)
            box_data = get_unit_3d_box_data(self.scanner, u_ptr)
            if not box_data: continue
            
            pos, bmin, bmax, R = box_data
            
            # 2. คำนวณพิกัด 8 มุมในโลก 3D
            corners_3d = calculate_3d_box_corners(pos, bmin, bmax, R)
            
            pts = []
            all_valid = True
            
            # 3. แปลง 8 มุมนั้นมาลงหน้าจอ 2D
            for c in corners_3d:
                res = world_to_screen(view_matrix, c[0], c[1], c[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                if res and res[2] >= 0.001: # เช็คว่าทุกมุมต้องอยู่หน้ากล้อง
                    pts.append((res[0], res[1]))
                else:
                    all_valid = False
                    break
                    
            if not all_valid or len(pts) != 8:
                continue
                
            drawn_count += 1
            
            # 4. วาดเส้น 12 เส้นประกอบเป็นกล่อง
            painter.setPen(QPen(QColor(255, 0, 0, 255), 2)) # สีแดงสด
            
            # คู่ของจุดที่จะลากเส้นเข้าหากัน (อิงตาม Array ด้านบน)
            edges = [
                (0,1), (1,2), (2,3), (3,0), # ฐานล่าง 4 เส้น
                (4,5), (5,6), (6,7), (7,4), # หลังคา 4 เส้น
                (0,4), (1,5), (2,6), (3,7)  # เสาเชื่อม 4 เส้น
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