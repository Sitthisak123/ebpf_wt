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
    """ แปลงพิกัด 3D เป็น 2D หน้าจอ (พร้อมเกราะป้องกัน NaN) """
    
    # 🚨 1. กรองขยะตั้งแต่ต้นทาง (ถ้าเป็น NaN หรือ Inf ให้ปัดทิ้งทันที!)
    if not (math.isfinite(pos_x) and math.isfinite(pos_y) and math.isfinite(pos_z)):
        return None

    # คำนวณค่า W (ความลึกของกล้อง / Perspective Divide)
    w = (pos_x * matrix[3]) + (pos_y * matrix[7]) + (pos_z * matrix[11]) + matrix[15]

    # ถ้าวัตถุอยู่หลังกล้อง หรือค่า w ผิดปกติ ให้ข้ามไป
    if w < 0.01 or not math.isfinite(w):
        return None

    # คำนวณค่าพิกัดหน้าจอจำลอง (Clip Space)
    clip_x = (pos_x * matrix[0]) + (pos_y * matrix[4]) + (pos_z * matrix[8]) + matrix[12]
    clip_y = (pos_x * matrix[1]) + (pos_y * matrix[5]) + (pos_z * matrix[9]) + matrix[13]

    # ปรับให้อยู่ในรูปแบบพิกัดมาตรฐาน (Normalized Device Coordinates: -1 ถึง 1)
    ndc_x = clip_x / w
    ndc_y = clip_y / w

    # ขยายพิกัดให้พอดีกับหน้าจอ
    screen_x = (screen_width / 2) * (1 + ndc_x)
    screen_y = (screen_height / 2) * (1 - ndc_y)

    # 🚨 2. กรองด่านสุดท้ายก่อนจะแปลงเป็น Int
    if not (math.isfinite(screen_x) and math.isfinite(screen_y)):
        return None

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

# ==========================================
# 🚀 ระบบ 3D Bounding Box (กล่อง 3 มิติ)
# ==========================================
OFF_UNIT_ROTATION = 0xB14
# 💡 หมายเหตุ: ถ้ากล่องเบี้ยวหรือเล็กไป ให้ลองเปลี่ยน BBMIN=0x238, BBMAX=0x244
OFF_UNIT_BBMIN = 0x230 
OFF_UNIT_BBMAX = 0x23C 

def get_unit_3d_box_data(scanner, u_ptr):
    """ ดึง Position, BBMin, BBMax และ Rotation Matrix """
    if u_ptr == 0: return None
    
    # 1. ดึงพิกัด (X, Y, Z)
    pos_data = scanner.read_mem(u_ptr + OFF_UNIT_X, 12)
    if not pos_data or len(pos_data) < 12: return None
    pos = struct.unpack("<fff", pos_data) 

    # 2. ดึง BBMin & BBMax (ขนาดกว้างยาวของตัวรถ)
    bbmin_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMIN, 12)
    bbmax_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMAX, 12)
    if not bbmin_data or not bbmax_data: return None
    
    bmin = list(struct.unpack("<fff", bbmin_data))
    bmax = list(struct.unpack("<fff", bbmax_data))
    
    # สลับค่าถ้า min > max (แก้บั๊กของเอนจิน)
    for i in range(3):
        if bmin[i] > bmax[i]:
            bmin[i], bmax[i] = bmax[i], bmin[i]

    # 3. ดึง Rotation Matrix (3x3 = 9 Floats = 36 bytes)
    rot_data = scanner.read_mem(u_ptr + OFF_UNIT_ROTATION, 36)
    if not rot_data or len(rot_data) < 36: return None
    R = struct.unpack("<9f", rot_data)
    
    return pos, tuple(bmin), tuple(bmax), R

def calculate_3d_box_corners(pos, bmin, bmax, R):
    """ คำนวณจุดยอดทั้ง 8 มุมของกล่อง 3 มิติในโลกเกม """
    local_center = [(bmin[i] + bmax[i]) * 0.5 for i in range(3)]
    local_ext = [(bmax[i] - bmin[i]) * 0.5 for i in range(3)]
    
    # ดึงแกนเวกเตอร์จาก Rotation Matrix
    axisX = [R[0], R[1], R[2]]
    axisY = [R[3], R[4], R[5]]
    axisZ = [R[6], R[7], R[8]]
    
    # Normalize ป้องกันสัดส่วนเบี้ยว
    def normalize(v):
        length = math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
        if length > 1e-12:
            return [v[0]/length, v[1]/length, v[2]/length]
        return [0.0, 0.0, 0.0]
        
    axisX = normalize(axisX)
    axisY = normalize(axisY)
    axisZ = normalize(axisZ)
    
    # หาจุดกึ่งกลางของโลก (World Center)
    worldCenter = [
        pos[0] + axisX[0]*local_center[0] + axisY[0]*local_center[1] + axisZ[0]*local_center[2],
        pos[1] + axisX[1]*local_center[0] + axisY[1]*local_center[1] + axisZ[1]*local_center[2],
        pos[2] + axisX[2]*local_center[0] + axisY[2]*local_center[1] + axisZ[2]*local_center[2]
    ]
    
    ex = [axisX[i] * local_ext[0] for i in range(3)]
    ey = [axisY[i] * local_ext[1] for i in range(3)]
    ez = [axisZ[i] * local_ext[2] for i in range(3)]
    
    corners = []
    # สร้าง 8 มุมจากการบวกลบเวกเตอร์ (เครื่องหมาย +- ของ X, Y, Z)
    signs = [
        (-1, -1, -1), ( 1, -1, -1), ( 1,  1, -1), (-1,  1, -1),
        (-1, -1,  1), ( 1, -1,  1), ( 1,  1,  1), (-1,  1,  1)
    ]
    
    for sx, sy, sz in signs:
        cx = worldCenter[0] + sx*ex[0] + sy*ey[0] + sz*ez[0]
        cy = worldCenter[1] + sx*ex[1] + sy*ey[1] + sz*ez[1]
        cz = worldCenter[2] + sx*ex[2] + sy*ey[2] + sz*ez[2]
        corners.append((cx, cy, cz))
        
    return corners

# ==========================================
# 🎯 ระบบ Quaternions สำหรับหมุนป้อมปืน (Weapon Bones)
# ==========================================
def quat_from_axis_angle(axis, angle):
    half_angle = angle * 0.5
    s = math.sin(half_angle)
    return (axis[0]*s, axis[1]*s, axis[2]*s, math.cos(half_angle))

def vec3_transform_quat(v, q):
    """ หมุนเวกเตอร์ v ด้วย Quaternion q """
    vx, vy, vz = v
    qx, qy, qz, qw = q
    
    tx = 2.0 * (qy*vz - qz*vy)
    ty = 2.0 * (qz*vx - qx*vz)
    tz = 2.0 * (qx*vy - qy*vx)
    
    cx = qy*tz - qz*ty
    cy = qz*tx - qx*tz
    cz = qx*ty - qy*tx
    
    return (vx + qw*tx + cx, vy + qw*ty + cy, vz + qw*tz + cz)

def vec3_transform_mat3(v, mat):
    """ หมุนเวกเตอร์ v ด้วย Rotation Matrix 3x3 ของตัวรถถัง """
    return (
        v[0]*mat[0][0] + v[1]*mat[1][0] + v[2]*mat[2][0],
        v[0]*mat[0][1] + v[1]*mat[1][1] + v[2]*mat[2][1],
        v[0]*mat[0][2] + v[1]*mat[1][2] + v[2]*mat[2][2]
    )

# 🚨 OFFSETS ปี 2022 (คุณต้องหาเลขปี 2026 มาเปลี่ยนตรงนี้!)
# 🚨 OFFSETS ปี 2026 (เจาะสดจาก RAM โดยแฮกเกอร์!)
# 🚨 OFFSETS ปี 2026 (Verified from your scan!)
# 🚨 OFFSETS ปี 2026 (เจาะทะลวงระดับ Deep X-Ray โดยแฮกเกอร์!)
OFF_UNIT_WEAPONS_PTR = 0xE78  # ชี้ไปที่ UnitWeapon (จาก 0xE00/0xE78)
OFF_ARMORY_POS_INFO  = 0x88   # X-Ray ยืนยันว่าเจอจุดหมุน 3D ที่นี่!
OFF_ARMORY_CTRL_WPN  = 0x1A0  # Array คุมองศาปืน (คู่หูของ 0x1B8)
OFF_ARMORY_WEAPONS   = 0x1B8  # Array ข้อมูลปืน

# --- ฟังก์ชันช่วยคำนวณ (Helper functions) ---
def vec3_add(v1, v2): return (v1[0]+v2[0], v1[1]+v2[1], v1[2]+v2[2])
def vec3_sub(v1, v2): return (v1[0]-v2[0], v1[1]-v2[1], v1[2]-v2[2])

def get_weapon_barrel(scanner, u_ptr, unit_pos, unit_rot_matrix):
    """ ดึงพิกัดปลายปืนและโคนปืน สำหรับวาด Laser ESP """
    if u_ptr == 0: return None
    
    # 1. เจาะเข้าไปที่ UnitWeapon
    raw_wpn_ptr = scanner.read_mem(u_ptr + OFF_UNIT_WEAPONS_PTR, 8)
    if not raw_wpn_ptr or len(raw_wpn_ptr) < 8: return None
    wpn_ptr = struct.unpack("<Q", raw_wpn_ptr)[0]
    if wpn_ptr == 0: return None

    # 2. อ่าน Pointer ของ Array หลัก (ใช้ Offset ที่สแกนเจอ)
    raw_pos_info = scanner.read_mem(wpn_ptr + OFF_ARMORY_POS_INFO, 8)
    raw_ctrl_wpn = scanner.read_mem(wpn_ptr + OFF_ARMORY_CTRL_WPN, 8)
    raw_weapons  = scanner.read_mem(wpn_ptr + OFF_ARMORY_WEAPONS, 8)
    
    if not all([raw_pos_info, raw_ctrl_wpn, raw_weapons]): return None
    
    pos_info_arr = struct.unpack("<Q", raw_pos_info)[0]
    ctrl_wpn_arr = struct.unpack("<Q", raw_ctrl_wpn)[0]
    weapons_arr  = struct.unpack("<Q", raw_weapons)[0]

    # 3. ดึงข้อมูลปืนกระบอกที่ 1 (Index 0)
    # เราอ่านมา 0x200 bytes เพื่อให้ครอบคลุมข้อมูลสำคัญ
    w_data = scanner.read_mem(weapons_arr, 0x110) 
    if not w_data or len(w_data) < 0x110: return None
    
    # ดึงค่า Index ของตัวควบคุม และทิศทาง Local
    ctrl_wpn_idx = struct.unpack_from("<h", w_data, 0x24)[0]
    w_up = struct.unpack_from("<fff", w_data, 0x9C)
    w_left = struct.unpack_from("<fff", w_data, 0xA8)

    # 4. ดึงพิกัดจุดหมุนและปลายปืน (Internal Info)
    # อ่านจาก Array ตัวแรก (Index 0)
    pos_info_ptr_raw = scanner.read_mem(pos_info_arr, 8)
    if not pos_info_ptr_raw: return None
    internal_info_ptr = struct.unpack("<Q", pos_info_ptr_raw)[0]
    
    i_data = scanner.read_mem(internal_info_ptr, 0x150)
    if not i_data or len(i_data) < 0x150: return None
    
    weapon_pos = struct.unpack_from("<fff", i_data, 0x34)  # ปลายกระบอกปืน (Local)
    yaw_pivot = struct.unpack_from("<fff", i_data, 0x9C)   # จุดหมุนป้อม
    pitch_pivot = struct.unpack_from("<fff", i_data, 0x104) # จุดหมุนลำกล้อง

    # 5. ดึงองศาการหัน (Yaw/Pitch) จาก ControllableWeapon
    yaw_pitch = [0.0, 0.0]
    if 0 <= ctrl_wpn_idx < 10: # กันเลขขยะ
        cw_data = scanner.read_mem(ctrl_wpn_arr + (ctrl_wpn_idx * 0x290), 0x60)
        if cw_data and len(cw_data) >= 0x60:
            rot_x, rot_y = struct.unpack_from("<ff", cw_data, 0x58)
            yaw_pitch = [rot_x * math.pi / 180.0, rot_y * math.pi / 180.0]

    # 6. คำนวณการหมุนด้วย Quaternions (ลำดับ: Pitch -> Yaw -> World)
    try:
        pitch_quat = quat_from_axis_angle(w_left, -yaw_pitch[1])
        yaw_quat = quat_from_axis_angle(w_up, yaw_pitch[0])

        def transform_point(point):
            # หมุนระดับลำกล้อง (Pitch)
            p = vec3_sub(point, pitch_pivot)
            p = vec3_transform_quat(p, pitch_quat)
            p = vec3_add(p, pitch_pivot)
            
            # หมุนระดับป้อม (Yaw)
            p = vec3_sub(p, yaw_pivot)
            p = vec3_transform_quat(p, yaw_quat)
            p = vec3_add(p, yaw_pivot)
            
            # แปลงเข้าสู่โลก (World Transformation)
            # หมุนตามตัวรถถัง (Matrix 3x3)
            p_final = (
                p[0]*unit_rot_matrix[0] + p[1]*unit_rot_matrix[3] + p[2]*unit_rot_matrix[6],
                p[0]*unit_rot_matrix[1] + p[1]*unit_rot_matrix[4] + p[2]*unit_rot_matrix[7],
                p[0]*unit_rot_matrix[2] + p[1]*unit_rot_matrix[5] + p[2]*unit_rot_matrix[8]
            )
            # บวกตำแหน่งรถถัง
            return vec3_add(p_final, unit_pos)

        final_barrel_tip = transform_point(weapon_pos)
        final_barrel_base = transform_point(pitch_pivot)
        
        # 🚨 ตรวจสอบว่าเป็นตัวเลขจริงไหม ก่อนส่งกลับไปวาดเส้น
        if not all(math.isfinite(x) for x in final_barrel_tip + final_barrel_base):
            return None

        return final_barrel_base, final_barrel_tip
        
    except Exception:
        return None