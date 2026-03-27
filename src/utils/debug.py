import time

# ==========================================
# 🐞 ระบบควบคุมการ Debug (เปิด/ปิด ได้ที่นี่)
# ==========================================
DEBUG_MODE = True      # 🎯 เปลี่ยนเป็น False เมื่อหาสาเหตุเจอแล้ว เพื่อลดอาการกระตุก
DEBUG_THROTTLE = 1.0   # 🎯 หน่วงเวลาโชว์ Log (วินาที) ป้องกัน Terminal ไหลเร็วเกินไป

_last_print_time = 0.0

def dprint(msg, force=False):
    """พิมพ์ Log ออกมาเฉพาะตอนที่เปิด DEBUG_MODE"""
    global _last_print_time
    if not DEBUG_MODE:
        return
        
    current_time = time.time()
    # ถ้า force=True ให้ปริ้นเลย ไม่ต้องรอรอบเวลา
    if force or (current_time - _last_print_time >= DEBUG_THROTTLE):
        print(f"[🐞 DEBUG] {msg}")
        if not force:
            _last_print_time = current_time

def dprint_frame_stats(fps, cgame_base, matrix_ok, total_units, valid_targets, my_unit_ok):
    """โชว์สถิติของเฟรมปัจจุบัน (จำกัดความเร็วการโชว์ตาม THROTTLE)"""
    global _last_print_time
    if not DEBUG_MODE: 
        return
    
    current_time = time.time()
    if current_time - _last_print_time >= DEBUG_THROTTLE:
        print("\n" + "="*45)
        print(f"🖥️ FPS          : {fps:.1f}")
        print(f"🎯 CGame Base   : {hex(cgame_base) if cgame_base else '❌ NOT FOUND'}")
        print(f"👁️ View Matrix  : {'✅ OK' if matrix_ok else '❌ FAILED (OFF_CAMERA_PTR / OFF_VIEW_MATRIX ขยับ)'}")
        print(f"🟢 My Unit      : {'✅ FOUND' if my_unit_ok else '❌ NOT FOUND (DAT_CONTROLLED_UNIT ขยับ)'}")
        print(f"📡 Total Units  : {total_units} units (ถ้าเป็น 0 แปลว่า OFF_AIR_UNITS / OFF_GROUND_UNITS ขยับ)")
        print(f"⚔️ Valid Targets: {valid_targets} targets")
        
        if total_units > 0 and valid_targets == 0:
            print("⚠️ WARNING: เจอศัตรูในแมป แต่โดนกรองทิ้งหมด! (อาจจะติด Team Filter หรือ Dead Filter)")
            
        print("="*45)
        _last_print_time = current_time