# validator.py
import struct
import math
from .mul import * # ดึง Offsets และฟังก์ชันดึงค่าจาก mul.py มาใช้

class OffsetValidator:
    def __init__(self, scanner, base_address):
        self.scanner = scanner
        self.base_address = base_address

    def check(self, name, success, info=""):
        status = "✅ [PASS]" if success else "❌ [FAIL]"
        print(f"{status} {name:20} : {info}")
        return success

    def run_diagnostics(self):
        print("\n" + "="*50)
        print("🔍 WAR THUNDER OFFSET DIAGNOSTICS (v_2_linux)")
        print("="*50)

        # 1. ตรวจสอบ CGame Base (DAT_MANAGER)
        cgame_base = get_cgame_base(self.scanner, self.base_address)
        if not self.check("CGame Base", is_valid_ptr(cgame_base), hex(cgame_base)):
            return False

        # 2. ตรวจสอบ View Matrix (หัวใจของ ESP)
        matrix = get_view_matrix(self.scanner, cgame_base)
        if matrix:
            # เช็คว่าค่า Matrix เป็นตัวเลขทศนิยมที่สมเหตุสมผล (ปกติอยู่ระหว่าง -5.0 ถึง 5.0)
            matrix_ok = all(math.isfinite(x) and -10.0 < x < 10.0 for x in matrix)
            self.check("View Matrix", matrix_ok, f"M[0]={matrix[0]:.2f}")
        else:
            self.check("View Matrix", False, "Read Failed")

        # 3. ตรวจสอบการดึงรายชื่อยูนิต (Unit List)
        units = get_all_units(self.scanner, cgame_base)
        if units:
            self.check("Unit List", True, f"Found {len(units)} units")
            
            # ลองดึงพิกัดยูนิตตัวแรกมาตรวจสอบ
            u_ptr, is_air = units[0]
            pos = get_unit_pos(self.scanner, u_ptr)
            if pos:
                # พิกัดต้องไม่ใช่ (0,0,0) และมีค่าไม่มหาศาลเกินไป
                pos_ok = any(abs(x) > 0.1 for x in pos) and all(abs(x) < 100000 for x in pos)
                self.check("Unit Position (0xD08)", pos_ok, f"X:{pos[0]:.1f}, Y:{pos[1]:.1f}")
            else:
                self.check("Unit Position (0xD08)", False, "Read Failed")
        else:
            self.check("Unit List", False, "No enemy units nearby (Try in Test Drive)")

        print("="*50 + "\n")
        return True