import struct
import math

# --- 🎯 2026 Verified Offsets ---
GHIDRA_BASE = 0x400000
DAT_MANAGER = 0x093924e0
MANAGER_OFFSET = DAT_MANAGER - GHIDRA_BASE
OFF_CAMERA_PTR = 0x5F0
OFF_VIEW_MATRIX = 0x1B8

OFF_UNIT_X = 0xb38
OFF_UNIT_ROTATION = 0xB14
OFF_UNIT_BBMIN = 0x230 
OFF_UNIT_BBMAX = 0x23C 

def get_cgame_base(scanner, base_addr):
    c_game_ptr_addr = base_addr + MANAGER_OFFSET
    raw_ptr = scanner.read_mem(c_game_ptr_addr, 8)
    if not raw_ptr or len(raw_ptr) < 8: return 0
    return struct.unpack("<Q", raw_ptr)[0]

def get_view_matrix(scanner, cgame_base):
    if cgame_base == 0: return None
    raw_cam_ptr = scanner.read_mem(cgame_base + OFF_CAMERA_PTR, 8)
    if not raw_cam_ptr or len(raw_cam_ptr) < 8: return None
    camera_ptr = struct.unpack("<Q", raw_cam_ptr)[0]
    if camera_ptr == 0: return None
    matrix_data = scanner.read_mem(camera_ptr + OFF_VIEW_MATRIX, 64)
    if not matrix_data or len(matrix_data) < 64: return None
    return struct.unpack("<16f", matrix_data)

def get_unit_pos(scanner, u_ptr):
    if u_ptr == 0: return None
    data = scanner.read_mem(u_ptr + OFF_UNIT_X, 12)
    if not data or len(data) < 12: return None
    val1, val2, val3 = struct.unpack("<fff", data)
    if not (math.isfinite(val1) and math.isfinite(val2) and math.isfinite(val3)): return None
    return (val1, val2, val3)

def world_to_screen(matrix, pos_x, pos_y, pos_z, screen_width, screen_height):
    w = (pos_x * matrix[3]) + (pos_y * matrix[7]) + (pos_z * matrix[11]) + matrix[15]
    if w < 0.01: return None
    clip_x = (pos_x * matrix[0]) + (pos_y * matrix[4]) + (pos_z * matrix[8]) + matrix[12]
    clip_y = (pos_x * matrix[1]) + (pos_y * matrix[5]) + (pos_z * matrix[9]) + matrix[13]
    ndc_x = clip_x / w
    ndc_y = clip_y / w
    screen_x = (screen_width / 2) * (1 + ndc_x)
    screen_y = (screen_height / 2) * (1 - ndc_y)
    return (int(screen_x), int(screen_y), w)

def get_all_units(scanner, cgame_base):
    if cgame_base == 0: return []
    raw_array_ptr = scanner.read_mem(cgame_base + 0x328, 8)
    raw_count = scanner.read_mem(cgame_base + 0x338, 4)
    if not raw_array_ptr or not raw_count: return []
    array_ptr = struct.unpack("<Q", raw_array_ptr)[0]
    count = struct.unpack("<I", raw_count)[0]
    if count <= 0 or count > 250 or array_ptr < 0x10000: return []
    units = []
    for i in range(count):
        raw_u_ptr = scanner.read_mem(array_ptr + (i * 8), 8)
        if raw_u_ptr:
            u_ptr = struct.unpack("<Q", raw_u_ptr)[0]
            if u_ptr != 0: units.append(u_ptr)
    return units

def get_unit_3d_box_data(scanner, u_ptr):
    if u_ptr == 0: return None
    pos_data = scanner.read_mem(u_ptr + OFF_UNIT_X, 12)
    if not pos_data or len(pos_data) < 12: return None
    pos = struct.unpack("<fff", pos_data) 
    bbmin_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMIN, 12)
    bbmax_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMAX, 12)
    if not bbmin_data or not bbmax_data: return None
    bmin = list(struct.unpack("<fff", bbmin_data))
    bmax = list(struct.unpack("<fff", bbmax_data))
    for i in range(3):
        if bmin[i] > bmax[i]: bmin[i], bmax[i] = bmax[i], bmin[i]
    rot_data = scanner.read_mem(u_ptr + OFF_UNIT_ROTATION, 36)
    if not rot_data or len(rot_data) < 36: return None
    R = struct.unpack("<9f", rot_data)
    return pos, tuple(bmin), tuple(bmax), R

def calculate_3d_box_corners(pos, bmin, bmax, R):
    local_center = [(bmin[i] + bmax[i]) * 0.5 for i in range(3)]
    local_ext = [(bmax[i] - bmin[i]) * 0.5 for i in range(3)]
    axisX, axisY, axisZ = [R[0], R[1], R[2]], [R[3], R[4], R[5]], [R[6], R[7], R[8]]
    def normalize(v):
        length = math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
        if length > 1e-12: return [v[0]/length, v[1]/length, v[2]/length]
        return [0.0, 0.0, 0.0]
    axisX, axisY, axisZ = normalize(axisX), normalize(axisY), normalize(axisZ)
    worldCenter = [
        pos[0] + axisX[0]*local_center[0] + axisY[0]*local_center[1] + axisZ[0]*local_center[2],
        pos[1] + axisX[1]*local_center[0] + axisY[1]*local_center[1] + axisZ[1]*local_center[2],
        pos[2] + axisX[2]*local_center[0] + axisY[2]*local_center[1] + axisZ[2]*local_center[2]
    ]
    ex = [axisX[i] * local_ext[0] for i in range(3)]
    ey = [axisY[i] * local_ext[1] for i in range(3)]
    ez = [axisZ[i] * local_ext[2] for i in range(3)]
    corners = []
    signs = [(-1, -1, -1), ( 1, -1, -1), ( 1,  1, -1), (-1,  1, -1), (-1, -1,  1), ( 1, -1,  1), ( 1,  1,  1), (-1,  1,  1)]
    for sx, sy, sz in signs:
        corners.append((
            worldCenter[0] + sx*ex[0] + sy*ey[0] + sz*ez[0],
            worldCenter[1] + sx*ex[1] + sy*ey[1] + sz*ez[1],
            worldCenter[2] + sx*ex[2] + sy*ey[2] + sz*ez[2]
        ))
    return corners

# -----------------------------------------------------
# 🎯 THE SMART BONE TRACKER (Scoring System)
# -----------------------------------------------------
def get_weapon_barrel(scanner, u_ptr, unit_pos, unit_rot_matrix, should_log=False):
    if u_ptr == 0: return None
    def is_valid_ptr(p): return 0x10000000000 < p < 0x7FFFFFFFFFFF

    if not hasattr(scanner, "bone_cache"): scanner.bone_cache = {}
    
    target_bone_index = -1
    wtm_ptr = 0

    try:
        # 1. โหลดจาก Cache ถ้าเคยหารถคันนี้เจอแล้ว
        if u_ptr in scanner.bone_cache:
            cache = scanner.bone_cache[u_ptr]
            anim_char_raw = scanner.read_mem(u_ptr + cache['anim_off'], 8)
            if anim_char_raw:
                anim_char = struct.unpack("<Q", anim_char_raw)[0]
                if is_valid_ptr(anim_char):
                    wtm_raw = scanner.read_mem(anim_char + 0x0, 8)
                    if wtm_raw:
                        wtm_ptr = struct.unpack("<Q", wtm_raw)[0]
                        target_bone_index = cache['bone_idx']

        # 2. ค้นหากระดูกใหม่ด้วยระบบ "Scoring" อัจฉริยะ!
        if wtm_ptr == 0 or target_bone_index == -1:
            best_score = -1
            best_idx = -1
            best_anim_off = 0
            
            # ใช้ Offset 0x1e8 ที่ท่านหาเจอเป็น Priority แรก (GeomNodeTree)
            tree_offsets = [0x1E8, 0x1E0, 0x1F0, 0x1D8, 0x200]
            
            for off in tree_offsets:
                raw_ptr = scanner.read_mem(u_ptr + off, 8)
                if not raw_ptr: continue
                tree_ptr = struct.unpack("<Q", raw_ptr)[0]
                if not is_valid_ptr(tree_ptr): continue
                
                raw_name = scanner.read_mem(tree_ptr + 0x40, 8)
                if not raw_name: continue
                name_ptr = struct.unpack("<Q", raw_name)[0]
                
                if is_valid_ptr(name_ptr):
                    names_block = scanner.read_mem(name_ptr, 0x4000)
                    if not names_block: continue
                    
                    # 💡 เริ่มการให้คะแนนกระดูก (Scoring System)
                    for i in range(400):
                        try:
                            str_offset = struct.unpack_from("<H", names_block, i * 2)[0]
                            if str_offset == 0 or str_offset >= len(names_block): continue
                            end_idx = names_block.find(b'\x00', str_offset)
                            if end_idx != -1:
                                bone_name = names_block[str_offset:end_idx].decode('utf-8', errors='ignore').lower().strip()
                                
                                score = -1
                                # ให้คะแนนตามความแม่นยำของชื่อ
                                if "bone_gun_barrel" in bone_name: score = 100
                                elif "gun_barrel" in bone_name: score = 80
                                elif "bone_gun" in bone_name: score = 60
                                elif "barrel" in bone_name: score = 40
                                elif "turret" in bone_name: score = 20
                                
                                # 🚨 บทลงโทษ: ถ้ามีคำพวกนี้ แบนทิ้งทันที (-100)
                                bad_words = ["mg", "machine", "smoke", "fuel", "water", "camera", "optic", "antenna", "suspension", "wheel", "track", "root"]
                                if any(bad in bone_name for bad in bad_words):
                                    score = -100
                                    
                                if score > best_score:
                                    best_score = score
                                    best_idx = i
                                    if should_log: print(f"  [+] อัปเดตเป้าปืนที่ดีที่สุด: '{bone_name}' (Score: {score})")
                        except: pass
                    
                    if best_idx != -1: break

            # ถ้าหา Index ได้แล้ว ให้ดึง WTM จาก AnimChar (Offset 0x228 ที่ท่านหาเจอ!)
            if best_idx != -1:
                anim_offsets = [0x228, 0x220, 0x230, 0x218]
                for a_off in anim_offsets:
                    anim_raw = scanner.read_mem(u_ptr + a_off, 8)
                    if anim_raw:
                        anim_char = struct.unpack("<Q", anim_raw)[0]
                        if is_valid_ptr(anim_char):
                            wtm_raw = scanner.read_mem(anim_char + 0x0, 8)
                            if wtm_raw:
                                w_ptr = struct.unpack("<Q", wtm_raw)[0]
                                if is_valid_ptr(w_ptr):
                                    wtm_ptr = w_ptr
                                    target_bone_index = best_idx
                                    # บันทึกลง Cache
                                    scanner.bone_cache[u_ptr] = {'anim_off': a_off, 'bone_idx': best_idx}
                                    break
                    if wtm_ptr != 0: break

        # 3. คำนวณวาดเลเซอร์จาก WTM
        if wtm_ptr != 0 and target_bone_index != -1:
            matrix_data = scanner.read_mem(wtm_ptr + (target_bone_index * 64), 64)
            if matrix_data and len(matrix_data) == 64:
                # 0x00 คือแกน X (เวกเตอร์ทิศทางหน้าปืน)
                fx, fy, fz = struct.unpack_from("<fff", matrix_data, 0x00) 
                # 0x30 คือพิกัด Local ของปืน
                bx, by, bz = struct.unpack_from("<fff", matrix_data, 0x30) 
                
                if math.isfinite(bx) and math.isfinite(fx):
                    length = 30.0 # ความยาวเลเซอร์
                    
                    if abs(bx) > 500.0 or abs(by) > 500.0:
                        # World Space (หายากใน AnimChar แต่ดักไว้ก่อน)
                        base_w = (bx, by, bz)
                        tip_w = (bx + (fx * length), by + (fy * length), bz + (fz * length))
                        return base_w, tip_w
                    else:
                        # Local Space (แปลงเข้าแกนโลกของรถถัง)
                        def to_world(lx, ly, lz):
                            wx = lx*unit_rot_matrix[0] + ly*unit_rot_matrix[3] + lz*unit_rot_matrix[6] + unit_pos[0]
                            wy = lx*unit_rot_matrix[1] + ly*unit_rot_matrix[4] + lz*unit_rot_matrix[7] + unit_pos[1]
                            wz = lx*unit_rot_matrix[2] + ly*unit_rot_matrix[5] + lz*unit_rot_matrix[8] + unit_pos[2]
                            return (wx, wy, wz)
                            
                        # ⚠️ ถ้าเลเซอร์ของรถบางคันพุ่งออกข้างๆ ให้แก้ +fx เป็น +fy หรือ +fz นะครับ 
                        # แต่ 99% ของ War Thunder ใช้แกน X (fx) เป็นด้านหน้าของปืน
                        return to_world(bx, by, bz), to_world(bx + (fx * length), by + (fy * length), bz + (fz * length))

    except Exception:
        pass
        
    return None