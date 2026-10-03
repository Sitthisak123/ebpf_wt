import sys
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QHBoxLayout, QPushButton
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QBrush, QPen, QFont


class CameraOverlayHUD(QWidget):
    """
    Transparent HUD Overlay ที่ลอยอยู่เหนือหน้าจอเกมชั่วคราว
    คอยจับเวลา 6 วินาทีต่อรอบ และแนะนำการหมุนกล้องสำหรับขั้นตอน getView
    """
    phaseCompleted = pyqtSignal(int)
    allPhasesCompleted = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.current_phase = 0
        self.phase_time_left = 6.0
        self.total_phase_duration = 6.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_tick)

        self.phases = [
            ("↔️ ขั้นตอนที่ 1/3: หันกล้อง ซ้าย-ขวา ช้าๆ (Yaw Scan)", "#2196F3"),
            ("↕️ ขั้นตอนที่ 2/3: ก้ม-เงยกล้อง ช้าๆ (Pitch Scan)", "#FF9800"),
            ("⏹️ ขั้นตอนที่ 3/3: ปล่อยเมาส์ อยู่นิ่งๆ (Stability Check)", "#4CAF50"),
        ]

        self._init_ui()
        self.resize(600, 160)
        self._center_top()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)

        self.title_label = QLabel("🎯 CAMERA TURNING SCANNER", self)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("color: #FFFFFF; font-size: 16px; font-weight: bold;")

        self.instruction_label = QLabel(self.phases[0][0], self)
        self.instruction_label.setAlignment(Qt.AlignCenter)
        self.instruction_label.setStyleSheet(f"color: {self.phases[0][1]}; font-size: 14px; font-weight: bold;")

        self.timer_label = QLabel("เวลาที่เหลือ: 6.0s", self)
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setStyleSheet("color: #E0E0E0; font-size: 20px; font-weight: bold;")

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #222228;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 4px;
            }
        """)

        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("ยกเลิก (Cancel)", self)
        self.btn_cancel.setFixedSize(120, 28)
        self.btn_cancel.setStyleSheet("background-color: #D32F2F; color: white; border-radius: 4px; font-weight: bold;")
        self.btn_cancel.clicked.connect(self.stop_and_hide)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addStretch()

        layout.addWidget(self.title_label)
        layout.addWidget(self.instruction_label)
        layout.addWidget(self.timer_label)
        layout.addWidget(self.progress_bar)
        layout.addLayout(btn_layout)

    def _center_top(self):
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            rect = screen.geometry()
            x = (rect.width() - self.width()) // 2
            y = 50
            self.move(x, y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Background box with translucent dark fill
        painter.setBrush(QBrush(QColor(18, 20, 26, 220)))
        painter.setPen(QPen(QColor(60, 70, 85, 230), 2))
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 12, 12)

    def start_guide(self):
        self.current_phase = 0
        self.phase_time_left = self.total_phase_duration
        self._update_display()
        self.show()
        self.raise_()
        self.timer.start(100)

    def _update_display(self):
        if self.current_phase < len(self.phases):
            text, color = self.phases[self.current_phase]
            self.instruction_label.setText(text)
            self.instruction_label.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")
            self.timer_label.setText(f"เวลาที่เหลือ: {self.phase_time_left:.1f}s")
            pct = int((self.phase_time_left / self.total_phase_duration) * 100)
            self.progress_bar.setValue(pct)

    def _on_tick(self):
        self.phase_time_left -= 0.1
        if self.phase_time_left <= 0:
            self.phaseCompleted.emit(self.current_phase)
            self.current_phase += 1
            if self.current_phase >= len(self.phases):
                self.timer.stop()
                self.allPhasesCompleted.emit()
                self.instruction_label.setText("✅ สแกนสำเร็จครบทุก Phase!")
                self.instruction_label.setStyleSheet("color: #4CAF50; font-size: 15px; font-weight: bold;")
                self.timer_label.setText("กำลังประมวลผล View Matrix...")
                QTimer.singleShot(1200, self.stop_and_hide)
                return
            else:
                self.phase_time_left = self.total_phase_duration

        self._update_display()

    def stop_and_hide(self):
        self.timer.stop()
        self.hide()
