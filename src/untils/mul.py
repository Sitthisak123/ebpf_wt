import struct
import math

# --- 🎯 2026 Verified Offsets from Ghidra (Linux gcc build) ---
GHIDRA_BASE = 0x400000

# Address ดิบจากหน้าจอ Ghidra
DAT_MANAGER         = 0x093924e0  # CGame Manager (ตัวแปร Global)
DAT_LOCAL_PLAYER    = 0x09394240  # Local Player Pointer
DAT_CONTROLLED_UNIT = 0x09394248  # The Tank you are actually driving

# 🧮 คำนวณหา Offset จริง (เอาไปบวกกับ Base Address ของเกมตอนรัน)
MANAGER_OFFSET         = DAT_MANAGER - GHIDRA_BASE         # = 0x8F924E0
LOCAL_PLAYER_OFFSET    = DAT_LOCAL_PLAYER - GHIDRA_BASE    # = 0x8F94240
CONTROLLED_UNIT_OFFSET = DAT_CONTROLLED_UNIT - GHIDRA_BASE # = 0x8F94248

# --- ฟังก์ชันอ่าน Pointer ของ CGame ---
def get_cgame_base(scanner, base_addr):
    # 🚨 ต้องเอา Base Address ของเกมมาบวกกับ Offset เสมอ!
    c_game_ptr_addr = base_addr + MANAGER_OFFSET
    
    # อ่านค่าที่อยู่ใน c_game_ptr_addr เพื่อดูว่า Object CGame จริงๆ อยู่ที่ไหน
    raw_ptr = scanner.read_mem(c_game_ptr_addr, 8)
    if not raw_ptr or len(raw_ptr) < 8:
        return 0
    return struct.unpack("<Q", raw_ptr)[0]

# --- 🚀 ฟังก์ชันใหม่: ดึง View Matrix สำหรับทำ ESP ---
OFF_CAMERA_PTR = 0x5F0
OFF_VIEW_MATRIX = 0x1B8

def get_view_matrix(scanner, cgame_base):
    if cgame_base == 0: return None
    
    # 1. เจาะทะลุ CGame ไปหา Camera Pointer
    raw_cam_ptr = scanner.read_mem(cgame_base + OFF_CAMERA_PTR, 8)
    if not raw_cam_ptr or len(raw_cam_ptr) < 8: return None
    camera_ptr = struct.unpack("<Q", raw_cam_ptr)[0]
    
    if camera_ptr == 0: return None
    
    # 2. อ่าน View Matrix (เมทริกซ์ 4x4 ใช้ Float 16 ตัว = 64 bytes)
    matrix_data = scanner.read_mem(camera_ptr + OFF_VIEW_MATRIX, 64)
    if not matrix_data or len(matrix_data) < 64: return None
    
    # ถอดรหัสออกมาเป็น Tuple ของ Float 16 ตัว
    return struct.unpack("<16f", matrix_data)

# --- ฟังก์ชันอ่านพิกัด (อัปเดตระบบกรองขยะ) ---
OFF_UNIT_X = 0xb38
OFF_UNIT_Z = 0xb3c # WT มักจะให้แกน Z เป็นความสูง (ขึ้น/ลง)
OFF_UNIT_Y = 0xb40

def get_unit_pos(scanner, u_ptr):
    if u_ptr == 0: return None
    
    data = scanner.read_mem(u_ptr + OFF_UNIT_X, 12)
    if not data or len(data) < 12: return None
    
    # ดึงค่าออกมาตรงๆ (ใน War Thunder: val3 คือความสูง Z)
    val1, val2, val3 = struct.unpack("<fff", data)
    
    if not (math.isfinite(val1) and math.isfinite(val2) and math.isfinite(val3)):
        return None
        
    # 🚨 ห้ามสลับแกน! ส่งค่ากลับตามที่ Memory จัดเรียงมาเป๊ะๆ
    return (val1, val2, val3)

def world_to_screen(matrix, pos_x, pos_y, pos_z, screen_width, screen_height):
    """
    แปลงพิกัด 3D ของเกม (X, Y, Z) ให้กลายเป็นพิกเซลบนหน้าจอ (Screen X, Screen Y)
    """
    # 1. คำนวณค่า W (ความลึกของกล้อง / Perspective Divide)
    # ใช้แกนที่ 4 ของเมทริกซ์ (indices 3, 7, 11, 15)
    w = (pos_x * matrix[3]) + (pos_y * matrix[7]) + (pos_z * matrix[11]) + matrix[15]

    # ถ้าค่า w ติดลบ หรือน้อยกว่า 0.01 แปลว่า "วัตถุนั้นอยู่ข้างหลังกล้อง" (ไม่ต้องวาด)
    if w < 0.01:
        return None

    # 2. คำนวณค่าพิกัดหน้าจอจำลอง (Clip Space)
    # แถว X (indices 0, 4, 8, 12)
    clip_x = (pos_x * matrix[0]) + (pos_y * matrix[4]) + (pos_z * matrix[8]) + matrix[12]
    
    # แถว Y (indices 1, 5, 9, 13)
    clip_y = (pos_x * matrix[1]) + (pos_y * matrix[5]) + (pos_z * matrix[9]) + matrix[13]

    # 3. ปรับให้อยู่ในรูปแบบพิกัดมาตรฐาน (Normalized Device Coordinates: -1 ถึง 1)
    ndc_x = clip_x / w
    ndc_y = clip_y / w

    # 4. ขยายพิกัดให้พอดีกับขนาดความละเอียดหน้าจอ (Resolution)
    # หมายเหตุ: แกน Y บนหน้าจอคอมพิวเตอร์จะกลับหัว (ด้านบนคือ 0, ด้านล่างคือ Height) เลยต้องใช้ 1 - ndc_y
    screen_x = (screen_width / 2) * (1 + ndc_x)
    screen_y = (screen_height / 2) * (1 - ndc_y)

    return (int(screen_x), int(screen_y), w)

# --- 🚀 อัปเกรด: ฟังก์ชันดึงรายชื่อรถถัง (ใช้ Offset ใหม่ที่คุณหาเจอ!) ---
OFF_UNIT_ARRAY = 0x328  # Pointer ชี้ไปหาจุดเริ่มต้นของรายชื่อรถ
OFF_UNIT_COUNT = 0x338  # จำนวนรถถัง

def get_all_units(scanner, cgame_base):
    if cgame_base == 0: return []
    
    # 1. อ่าน Array Pointer และ Count
    raw_array_ptr = scanner.read_mem(cgame_base + OFF_UNIT_ARRAY, 8)
    raw_count = scanner.read_mem(cgame_base + OFF_UNIT_COUNT, 4)
    
    if not raw_array_ptr or not raw_count: return []
    
    array_ptr = struct.unpack("<Q", raw_array_ptr)[0]
    count = struct.unpack("<I", raw_count)[0]
    
    # กรองขยะเบื้องต้น
    if count <= 0 or count > 250 or array_ptr < 0x10000: return []
    
    units = []
    
    # 2. สูบรายชื่อทั้งหมดออกมา (ทำแบบดึงทีละคันเหมือนโค้ดคุณ)
    for i in range(count):
        raw_u_ptr = scanner.read_mem(array_ptr + (i * 8), 8)
        if raw_u_ptr:
            u_ptr = struct.unpack("<Q", raw_u_ptr)[0]
            if u_ptr != 0:
                units.append(u_ptr)
                
    return units