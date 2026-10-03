import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class BaseStepModule:
    """
    Abstract Base Module สำหรับทุกขั้นตอนใน Pipeline ของ Offset Repair Tool
    แต่ละไฟล์ใน tools/offset_repair/modules/ จะสืบทอดจากคลาสนี้
    """
    def __init__(self, step_id, step_index, step_title, step_desc):
        self.step_id = step_id
        self.step_index = step_index
        self.step_title = step_title
        self.step_desc = step_desc
        self.preflight_instructions = ""
        self.candidates = []
        self.selected_candidate = None
        self.comparison_data = []
        self.is_verified = False
        self.verified_message = ""

    def check_preflight(self, game_ctx, snapshot_db) -> tuple[bool, str]:
        """
        ตรวจเช็คเงื่อนไขเบื้องต้นก่อนสแกน (เช่น ต้องเข้า Test Drive, ยูนิตต้องตรงกับ Snapshot)
        Return: (is_ok: bool, message: str)
        """
        if not game_ctx.is_connected:
            return False, "เกมยังไม่ได้เปิด หรือยังไม่พบ Process 'aces'"
        return True, "พร้อมดำเนินการ"

    def scan(self, game_ctx, snapshot_db, shared_state) -> list[dict]:
        """
        สแกนค้นหา Candidates ใน Memory
        Return: list of candidate dicts:
        [
            {
                "offset": 0x1234,
                "label": "Candidate A (0x1234)",
                "score": 95.0,
                "is_default": True,
                "extra": {}
            }, ...
        ]
        """
        raise NotImplementedError

    def compare(self, game_ctx, snapshot_db, selected_candidate, shared_state) -> list[dict]:
        """
        เปรียบเทียบข้อมูล Live ในเกมกับ Snapshot ทุกตัว
        Return: list of diff dicts:
        [
            {
                "field": "Speed",
                "live_val": "795.0 m/s",
                "snap_val": "795.0 m/s",
                "status": "match", # 'match', 'mismatch', 'warn'
                "notes": "ตรงกับ Snapshot T-34"
            }, ...
        ]
        """
        raise NotImplementedError

    def verify(self, game_ctx, selected_candidate, shared_state) -> tuple[bool, str]:
        """
        ทดสอบเงื่อนไขยืนยันความถูกต้องของ Candidate
        Return: (is_valid: bool, reason: str)
        """
        if not selected_candidate:
            return False, "ยังไม่ได้เลือก Candidate"
        return True, "ตรวจสอบผ่านเกณฑ์"

    def export_offsets(self, selected_candidate, shared_state) -> dict[str, int]:
        """
        แปลง Candidate ที่เลือกให้เป็น dict ของชื่อตัวแปร Offset และค่า Hex/Int
        ที่จะถูกนำไปบันทึกลง config/offsets.json
        """
        return {}

    def build_custom_widget(self, parent_widget, controller=None):
        """
        วิดเจ็ตส่วนเพิ่มเติมเฉพาะทาง (ถ้ามี) เช่น ปุ่มเปิด Overlay หรือปุ่มพิเศษ
        """
        return None
