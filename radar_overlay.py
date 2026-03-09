import sys
import time
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont

# นำเข้าเครื่องมือสแกนเนอร์และสูตรคำนวณจากไฟล์ของคุณ
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base, get_view_matrix, world_to_screen, get_unit_pos, get_all_units

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
            pos = get_unit_pos(self.scanner, u_ptr)
            if not pos: continue 
            
            ex, ey, ez = pos # ez คือพิกัด "ฐานรถ/พื้นดิน" ที่แม่นยำที่สุด
            
            # โปรเจกต์จุดเดียวที่ "ฐานรถ" (ที่คุณบอกว่าตำแหน่งเป๊ะทุกมุมมอง!)
            screen_pos = world_to_screen(view_matrix, ex, ey, ez, SCREEN_WIDTH, SCREEN_HEIGHT)

            if screen_pos:
                sx, sy, w = screen_pos # w คือระยะห่าง (Depth)

                # ถ้ารถอยู่หลังกล้อง ให้ข้ามไป
                if w < 0.1: continue

                # 📐 1. FOV Dynamic Scale (คำนวณขนาดจากเลนส์กล้องของจริง!)
                # view_matrix[5] คือค่าความซูม (FOV) ที่เปลี่ยนไปมาตอนส่องกล้อง
                # สมมติว่ารถถังมีความสูงประมาณ 3.0 เมตรในโลก 3D
                real_height = 3.0 
                
                # สูตรคำนวณความสูงหน้าจอ: (ความสูงจริง * ค่าซูม / ระยะห่าง) * ครึ่งนึงของจอ
                box_h = int((real_height * abs(view_matrix[5]) / w) * (SCREEN_HEIGHT / 2))
                box_w = int(box_h * 1.5) # ให้ความกว้างเป็น 1.5 เท่าของความสูง
                
                # ลิมิตขนาดกล่อง ไม่ให้เล็กจนมองไม่เห็น หรือใหญ่จนบั๊กบังจอ
                box_w = max(8, min(box_w, 800))
                box_h = max(8, min(box_h, 800))
                
                # 🚨 2. ล็อคขอบล่างของกล่อง (Anchor to Bottom)
                # sx, sy คือพิกัดที่ติดพื้นดิน (ตีนตะขาบ)
                draw_x = sx - (box_w // 2)
                draw_y = sy - box_h 
                
                # อนุญาตให้วาดได้แม้มุมกล่องล้นขอบจอ เช็คแค่จุดศูนย์กลางที่พื้น
                if -500 <= sx <= SCREEN_WIDTH + 500 and -500 <= sy <= SCREEN_HEIGHT + 500:
                    drawn_count += 1
                    # วาดกล่อง (สีแดงสด)
                    painter.setPen(QPen(QColor(255, 0, 0, 255), 2))
                    painter.drawRect(int(draw_x), int(draw_y), int(box_w), int(box_h))
                    
                    # 🚨 เติม int(sy) ลงไปตรงนี้ครับ!
                    painter.setPen(QPen(QColor(255, 0, 0, 150), 1))
                    painter.drawLine(SCREEN_WIDTH // 2, SCREEN_HEIGHT, int(sx), int(sy))


        # ---------------------------------------------------------
        # 4. อัปเดตข้อมูลบนจอ และ Print ลง Terminal
        # ---------------------------------------------------------
        painter.setPen(QColor(255, 255, 0, 255)) # สีเหลือง
        painter.drawText(20, 60, f"Units Found: {len(all_units)} | Valid Pos: {valid_pos_count} | Drawn on Screen: {drawn_count}")

        if should_log:
            print(f"[*] Log (1s) -> CGame: {hex(cgame_base)} | Units: {len(all_units)} | On-Screen: {drawn_count}")

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