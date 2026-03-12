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

OFF_AIR_MOVEMENT = 0x18       # 🎯 2026 Verified: Pointer ฟิสิกส์เครื่องบิน
OFF_AIR_VEL = 0x0318          # 🎯 2026 Verified: ความเร็วเครื่องบิน (แกน X, Y, Z)

OFF_GROUND_MOVEMENT = 0x1b30  # 🎯 2026 Verified: Pointer รถถัง (ขยับจาก 1b38 เป็น 1b30)
OFF_GROUND_VEL = 0x54         # 🎯 2026 Verified: ความเร็วรถถัง

def is_valid_ptr(p): 
    return 0x10000 < p < 0xFFFFFFFFFFFFFFFF

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

def get_all_units(scanner, cgame_base):
    if cgame_base == 0: return []
    units = []
    
    # ⚡ [OPTIMIZED]: กวาด Array แบบ Bulk Read และแยก Air/Ground ทันที!
    # 0x310 = Air (True), 0x328 = Ground (False)
    for off, is_air in [(0x310, True), (0x328, False)]:
        raw_array_ptr = scanner.read_mem(cgame_base + off, 8)
        raw_count = scanner.read_mem(cgame_base + off + 16, 4) 
        if raw_array_ptr and raw_count:
            array_ptr = struct.unpack("<Q", raw_array_ptr)[0]
            count = struct.unpack("<I", raw_count)[0]
            if 0 < count < 250 and is_valid_ptr(array_ptr):
                # 🚀 Bulk Read: อ่าน Pointer ทั้งหมดในคำสั่งเดียว! ประหยัด CPU มหาศาล
                ptr_data = scanner.read_mem(array_ptr, count * 8)
                if ptr_data:
                    for i in range(count):
                        u_ptr = struct.unpack_from("<Q", ptr_data, i * 8)[0]
                        if is_valid_ptr(u_ptr):
                            units.append((u_ptr, is_air)) # 👈 แปะป้าย is_air ทันที!
                            
    # ลบตัวซ้ำ (โดยรักษาลำดับและข้อมูล is_air ไว้)
    return list({u[0]: u for u in units}.values())

def get_unit_3d_box_data(scanner, u_ptr):
    if u_ptr == 0: return None
    pos_data = scanner.read_mem(u_ptr + OFF_UNIT_X, 12)
    if not pos_data or len(pos_data) < 12: return None
    pos = struct.unpack("<fff", pos_data) 
    
    # ⚡ [OPTIMIZED]: อ่าน Box Min/Max แบบรวบยอด (24 Bytes) ลด Read Calls
    box_data = scanner.read_mem(u_ptr + OFF_UNIT_BBMIN, 24)
    if not box_data or len(box_data) < 24: return None
    bmin = list(struct.unpack_from("<fff", box_data, 0))
    bmax = list(struct.unpack_from("<fff", box_data, 12))
    
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

def get_weapon_barrel(scanner, u_ptr, unit_pos, unit_rot_matrix, should_log=False):
    if u_ptr == 0: return None
    if not hasattr(scanner, "bone_cache"): scanner.bone_cache = {}
    target_bone_index = -1
    wtm_ptr = 0

    try:
        if u_ptr in scanner.bone_cache:
            cache = scanner.bone_cache[u_ptr]
            anim_char_raw = scanner.read_mem(u_ptr + cache['anim_off'], 8)
            if anim_char_raw: 
                anim_char = struct.unpack("<Q", anim_char_raw)[0]
                if is_valid_ptr(anim_char):
                    wtm_raw = scanner.read_mem(anim_char + 0x0, 8)
                    if wtm_raw:
                        w_ptr = struct.unpack("<Q", wtm_raw)[0]
                        if is_valid_ptr(w_ptr):
                            target_idx = cache['bone_idx']
                            matrix_data = scanner.read_mem(w_ptr + (target_idx * 64), 64)
                            if matrix_data:
                                bx, by, bz = struct.unpack_from("<fff", matrix_data, 0x30)
                                if abs(bx) < 5000 and abs(by) < 5000:
                                    wtm_ptr = w_ptr
                                    target_bone_index = target_idx
                                else: del scanner.bone_cache[u_ptr]
                            else: del scanner.bone_cache[u_ptr]

        if wtm_ptr == 0 or target_bone_index == -1:
            best_score, best_idx = -1, -1
            for off in [0x1E8, 0x1E0, 0x1F0, 0x1D8, 0x200, 0x210, 0x228, 0x1C8]:
                raw_ptr = scanner.read_mem(u_ptr + off, 8)
                if not raw_ptr: continue
                tree_ptr = struct.unpack("<Q", raw_ptr)[0]
                if not is_valid_ptr(tree_ptr): continue
                raw_name = scanner.read_mem(tree_ptr + 0x40, 8)
                if not raw_name: continue
                name_ptr = struct.unpack("<Q", raw_name)[0]
                if not is_valid_ptr(name_ptr): continue
                names_block = scanner.read_mem(name_ptr, 0x4000)
                if not names_block: continue
                    
                for i in range(400):
                    try:
                        str_offset = struct.unpack_from("<H", names_block, i * 2)[0]
                        if str_offset == 0 or str_offset >= len(names_block): continue
                        end_idx = names_block.find(b'\x00', str_offset)
                        if end_idx != -1:
                            bone_name = names_block[str_offset:end_idx].decode('utf-8', errors='ignore').lower().strip()
                            score = -1
                            if "bone_gun_barrel" in bone_name: score = 100
                            elif "gun_barrel" in bone_name: score = 80
                            elif "bone_gun" in bone_name: score = 60
                            elif "barrel" in bone_name: score = 40
                            if any(b in bone_name for b in ["mg", "machine", "smoke", "fuel", "water", "camera", "optic", "antenna", "suspension", "wheel", "track", "root"]): score = -100
                            if score > best_score: best_score, best_idx = score, i
                    except: pass
                if best_idx != -1: break

            if best_idx != -1:
                for a_off in [0x228, 0x220, 0x230, 0x218, 0x240, 0x200, 0x250]:
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
                                    scanner.bone_cache[u_ptr] = {'anim_off': a_off, 'bone_idx': best_idx}
                                    break

        if wtm_ptr != 0 and target_bone_index != -1:
            matrix_data = scanner.read_mem(wtm_ptr + (target_bone_index * 64), 64)
            if matrix_data and len(matrix_data) == 64:
                fx, fy, fz = struct.unpack_from("<fff", matrix_data, 0x00) 
                bx, by, bz = struct.unpack_from("<fff", matrix_data, 0x30) 
                if math.isfinite(bx) and math.isfinite(fx):
                    if abs(bx) < 0.1 and abs(by) < 0.1 and abs(bz) < 0.1: return None
                    length = 30.0 
                    if abs(bx) > 500.0 or abs(by) > 500.0:
                        return (bx, by, bz), (bx + (fx * length), by + (fy * length), bz + (fz * length))
                    else:
                        def to_world(lx, ly, lz):
                            return (lx*unit_rot_matrix[0] + ly*unit_rot_matrix[3] + lz*unit_rot_matrix[6] + unit_pos[0],
                                    lx*unit_rot_matrix[1] + ly*unit_rot_matrix[4] + lz*unit_rot_matrix[7] + unit_pos[1],
                                    lx*unit_rot_matrix[2] + ly*unit_rot_matrix[5] + lz*unit_rot_matrix[8] + unit_pos[2])
                        return to_world(bx, by, bz), to_world(bx + (fx * length), by + (fy * length), bz + (fz * length))
    except Exception: pass
    return None

def get_local_team(scanner, base_addr):
    try:
        control_ptr = struct.unpack("<Q", scanner.read_mem(base_addr + (0x09394248 - 0x400000), 8))[0]
        team = struct.unpack("<B", scanner.read_mem(control_ptr + 0xDE8, 1))[0]
        return control_ptr, team
    except: return 0, 0

def get_unit_status(scanner, u_ptr):
    if u_ptr == 0: return None
    try:
        # ⚡ [OPTIMIZED]: อ่าน State และ Team พร้อมกันประหยัด 1 Call (ห่างกัน 128 bytes)
        status_data = scanner.read_mem(u_ptr + 0xD68, 132) 
        if not status_data: return None
        state = struct.unpack_from("<H", status_data, 0)[0]
        team = struct.unpack_from("<B", status_data, 0x80)[0]
        
        unit_name = "UNKNOWN"
        info_raw = scanner.read_mem(u_ptr + 0xDF8, 8) 
        if info_raw:
            info_ptr = struct.unpack("<Q", info_raw)[0]
            if is_valid_ptr(info_ptr):
                # 🚀 ตัดระบบหา Family ID ทิ้ง! (เพราะเราแยกประเภทมาจาก Source Array เรียบร้อยแล้ว)
                name_ptr_raw = scanner.read_mem(info_ptr + 0x28, 8)
                if name_ptr_raw:
                    name_ptr = struct.unpack("<Q", name_ptr_raw)[0]
                    if is_valid_ptr(name_ptr):
                        str_data = scanner.read_mem(name_ptr, 32)
                        if str_data:
                            try:
                                raw_str = str_data.split(b'\x00')[0].decode('utf-8', errors='ignore')
                                unit_name = "".join([c for c in raw_str if c.isalnum() or c in '-_'])
                            except: pass
                            
        reload_val = -1
        reload_raw = scanner.read_mem(u_ptr + 0x8E8, 4)
        if reload_raw:
            try:
                reload_val = struct.unpack("<i", reload_raw)[0]
            except: pass
                
        return team, state, unit_name, reload_val
    except Exception:
        return None
    

# ===================================================
# นำไปแทนที่ฟังก์ชัน get_unit_velocity เดิมด้านล่างสุดของ mul.py
# ===================================================
def get_unit_velocity(scanner, u_ptr, is_air):
    if u_ptr == 0: return None
    try:
        # --- ✈️ สำหรับเครื่องบิน (Air Units) ---
        if is_air:
            # 1. เข้าไปที่ Pointer โครงสร้างการบิน
            raw_move_ptr = scanner.read_mem(u_ptr + OFF_AIR_MOVEMENT, 8)
            if not raw_move_ptr: return None
            move_ptr = struct.unpack("<Q", raw_move_ptr)[0]
            if not is_valid_ptr(move_ptr): return None
            
            # 2. ดึงค่า Velocity แกน X, Y, Z แบบ Float (32-bit) รวม 12 Bytes
            vel_data = scanner.read_mem(move_ptr + OFF_AIR_VEL, 12)
            if not vel_data or len(vel_data) < 12: return None
            
            vx, vy, vz = struct.unpack("<fff", vel_data)
            
            # 3. กรองค่าขยะเพื่อความปลอดภัย
            if not (math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz)): return None
            if abs(vx) > 5000 or abs(vy) > 5000 or abs(vz) > 5000: return None
            return (vx, vy, vz)
            
        # --- 🚙 สำหรับรถถัง (Ground Units) ---
        else:
            raw_move_ptr = scanner.read_mem(u_ptr + OFF_GROUND_MOVEMENT, 8)
            if not raw_move_ptr: return None
            move_ptr = struct.unpack("<Q", raw_move_ptr)[0]
            if not is_valid_ptr(move_ptr): return None
            
            vel_data = scanner.read_mem(move_ptr + OFF_GROUND_VEL, 12)
            if not vel_data or len(vel_data) < 12: return None
            
            vx, vy, vz = struct.unpack("<fff", vel_data)
            
            if not (math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz)): return None
            if abs(vx) > 5000 or abs(vy) > 5000 or abs(vz) > 5000: return None
            return (vx, vy, vz)
            
    except Exception:
        return None