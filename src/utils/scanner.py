import os
import sys
import re
import math
import struct
import subprocess
from collections import Counter

# ==========================================
# 🛠️ คลาสสำหรับอ่าน Memory & Pattern Scanning
# ==========================================
class MemoryScanner:
    def __init__(self, pid):
        self.pid = pid
        self.mem_fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)

    def read_mem(self, address, size):
        if address is None or address <= 0x10000:
            return None
        try:
            os.lseek(self.mem_fd, address, os.SEEK_SET)
            return os.read(self.mem_fd, size)
        except OSError:
            return None
        except Exception:
            return None

    def find_all_patterns(self, pattern_hex):
        """ค้นหาลายนิ้วมือหาตัวแปร Global (DAT_MANAGER, MY_UNIT)"""
        regex_bytes = b""
        for chunk in pattern_hex.split():
            if chunk == "?" or chunk == "??": regex_bytes += b"."
            else:
                b = bytes([int(chunk, 16)])
                if b in b".^$*+?{}\\[]|()": regex_bytes += b"\\" + b
                else: regex_bytes += b

        results = []
        try:
            with open(f"/proc/{self.pid}/maps", "r") as f:
                for line in f:
                    if "aces" in line and "r-xp" in line:
                        parts = line.split()
                        start_addr, end_addr = [int(x, 16) for x in parts[0].split("-")]
                        size = end_addr - start_addr
                        
                        os.lseek(self.mem_fd, start_addr, os.SEEK_SET)
                        mem_dump = b""
                        bytes_left = size
                        while bytes_left > 0:
                            chunk_size = min(bytes_left, 0x2000000)
                            chunk = os.read(self.mem_fd, chunk_size)
                            if not chunk: break
                            mem_dump += chunk
                            bytes_left -= len(chunk)
                            
                        for match in re.finditer(regex_bytes, mem_dump, re.DOTALL):
                            match_offset = match.start()
                            instruction_addr = start_addr + match_offset
                            relative_offset = struct.unpack("<i", mem_dump[match_offset + 3 : match_offset + 7])[0]
                            target_addr = instruction_addr + 7 + relative_offset
                            results.append(target_addr)
        except Exception as e: pass
        return results
    def find_matrix_chain(self, pattern_hex):
        """
        สแกนหาชุดคำสั่งต่อเนื่องและสกัดเอา Offset 4 ไบต์ออกมาจากตำแหน่ง ??
        ตัวอย่าง: "41 88 B4 14 ?? 01 00 00 41 88 B4 14 ?? 01 00 00"
        """
        import re
        # แปลง Pattern ให้เป็น Regex
        regex_parts = []
        for chunk in pattern_hex.split():
            if chunk == "??": regex_parts.append(b"(.)") # ดักจับ 1 ไบต์ตรง ??
            else: regex_parts.append(re.escape(bytes([int(chunk, 16)])))
        
        pattern_re = b"".join(regex_parts)
        results = []

        try:
            with open(f"/proc/{self.pid}/maps", "r") as f:
                for line in f:
                    if "aces" in line and "r-xp" in line:
                        parts = line.split()
                        start_addr, end_addr = [int(x, 16) for x in parts[0].split('-')]
                        
                        os.lseek(self.mem_fd, start_addr, os.SEEK_SET)
                        chunk = os.read(self.mem_fd, end_addr - start_addr)
                        
                        for match in re.finditer(pattern_re, chunk):
                            # match.group(1) คือไบต์แรก (?? ตัวที่ 1)
                            # match.group(2) คือไบต์สอง (?? ตัวที่ 2)
                            off1 = int(match.group(1)[0]) | 0x100 # รวมกับ 01 00 00
                            off2 = int(match.group(2)[0]) | 0x100 
                            results.append((off1, off2))
            return results
        except Exception as e:
            print(f"  [-] Error in chain scan: {e}")
            return []
    
    def find_visual_dna(self, pattern_hex):
        """
        สแกนหาชุดคำสั่ง 3 ชั้น เพื่อสกัดเอา Camera Offset ที่แท้จริง
        Pattern: [MOV 6EC] -> [MOV 670 (Target)] -> [MOVUPS 6D4]
        """
        import re
        regex_parts = []
        for chunk in pattern_hex.split():
            if chunk == "??": regex_parts.append(b"(.)")
            else: regex_parts.append(re.escape(bytes([int(chunk, 16)])))
        
        pattern_re = b"".join(regex_parts)
        results = []

        try:
            with open(f"/proc/{self.pid}/maps", "r") as f:
                for line in f:
                    if "aces" in line and "r-xp" in line:
                        parts = line.split()
                        start_addr, end_addr = [int(x, 16) for x in parts[0].split('-')]
                        os.lseek(self.mem_fd, start_addr, os.SEEK_SET)
                        chunk = os.read(self.mem_fd, end_addr - start_addr)
                        
                        for match in re.finditer(pattern_re, chunk):
                            # สกัด Offset จากกลุ่มที่ 2 (?? ตัวที่ 3 และ 4)
                            off_low = match.group(3)[0]
                            off_high = match.group(4)[0]
                            offset = off_low | (off_high << 8)
                            results.append(offset)
            return results
        except: return []
        
    def find_all_struct_offsets(self, pattern_hex, offset_index=3):
        """ค้นหาลายนิ้วมือโครงสร้างรถถัง (Struct) แล้วคืนค่าตัวเลขระยะห่าง"""
        regex_bytes = b""
        for chunk in pattern_hex.split():
            if chunk == "?" or chunk == "??": regex_bytes += b"."
            else:
                b = bytes([int(chunk, 16)])
                if b in b".^$*+?{}\\[]|()": regex_bytes += b"\\" + b
                else: regex_bytes += b

        results = []
        try:
            with open(f"/proc/{self.pid}/maps", "r") as f:
                for line in f:
                    if "aces" in line and "r-xp" in line:
                        parts = line.split()
                        start_addr, end_addr = [int(x, 16) for x in parts[0].split("-")]
                        os.lseek(self.mem_fd, start_addr, os.SEEK_SET)
                        mem_dump = os.read(self.mem_fd, end_addr - start_addr)
                        
                        for match in re.finditer(regex_bytes, mem_dump, re.DOTALL):
                            match_offset = match.start()
                            # 🎯 ดึงเลข 4 Bytes ออกมาเป็น Offset เลย!
                            struct_offset = struct.unpack("<i", mem_dump[match_offset + offset_index : match_offset + offset_index + 4])[0]
                            results.append(struct_offset)
        except Exception as e: pass
        return results

    def __del__(self):
        try: os.close(self.mem_fd)
        except: pass

def get_game_pid():
    try:
        pid_str = subprocess.check_output(["pgrep", "aces"]).decode().strip().split('\n')[0]
        return int(pid_str)
    except:
        sys.exit(1)

def get_game_base_address(pid):
    try:
        with open(f"/proc/{pid}/maps", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 6 and parts[5].endswith("aces"): 
                    return int(parts[0].split("-")[0], 16)
    except: pass
    return 0


def _looks_like_view_matrix(matrix_data):
    if not matrix_data or len(matrix_data) < 64:
        return False
    try:
        values = struct.unpack("<16f", matrix_data[:64])
    except Exception:
        return False
    if not all(math.isfinite(v) for v in values):
        return False
    if any(abs(v) > 1e6 for v in values):
        return False
    non_zero = sum(1 for v in values if abs(v) > 1e-6)
    return non_zero >= 6

# ==========================================
# 🚀 ระบบตั้งค่า Offset อัตโนมัติ (Master Auto-Updater)
# ==========================================
def init_dynamic_offsets(scanner, base_address):
    import src.utils.mul as mul
    from collections import Counter
    print("\n" + "="*55)
    print("🚀 [SYSTEM BOOT] กำลังสแกนหา Offsets ด้วย AI สถิติ...")
    print("="*55)
    
    manager_ok = hero_ok = False
    
    # ---------------------------------------------------------
    # 🎯 Phase 1: สแกนหา CGame Base (DAT_MANAGER)
    # ---------------------------------------------------------
    print("[*] 🔍 1/5 ค้นหา CGame Base (DAT_MANAGER)...")
    patterns_manager = ["48 8B 05 ? ? ? ? 48 85 C0", "48 8B 3D ? ? ? ? 48 85 FF"]
    all_manager_targets = []
    manager_candidates = []
    for p in patterns_manager:
        all_manager_targets.extend(scanner.find_all_patterns(p))

    if all_manager_targets:
        valid_targets = [t for t in all_manager_targets if t > base_address and (t - base_address) < 0x20000000]
        counter = Counter(valid_targets)
        for target_addr, count in counter.most_common(80):
            raw_ptr = scanner.read_mem(target_addr, 8)
            if not raw_ptr or len(raw_ptr) < 8:
                continue
            cgame_ptr = struct.unpack("<Q", raw_ptr)[0]
            if not mul.is_valid_ptr(cgame_ptr):
                continue

            struct_score = 0
            for unit_off, _ in (mul.OFF_AIR_UNITS, mul.OFF_GROUND_UNITS):
                raw_array_ptr = scanner.read_mem(cgame_ptr + unit_off, 8)
                raw_count = scanner.read_mem(cgame_ptr + unit_off + 16, 4)
                if not raw_array_ptr or len(raw_array_ptr) < 8 or not raw_count or len(raw_count) < 4:
                    continue
                array_ptr = struct.unpack("<Q", raw_array_ptr)[0]
                unit_count = struct.unpack("<I", raw_count)[0]
                if 0 <= unit_count <= 2048:
                    struct_score += 1
                if unit_count > 0 and mul.is_valid_ptr(array_ptr):
                    struct_score += 2

            manager_candidates.append({
                "target_addr": target_addr,
                "dynamic_offset": target_addr - base_address,
                "votes": count,
                "cgame_ptr": cgame_ptr,
                "struct_score": struct_score,
            })

    if manager_candidates:
        best_manager = max(manager_candidates, key=lambda c: (c["struct_score"], c["votes"]))
        mul.MANAGER_OFFSET = best_manager["dynamic_offset"]
        manager_ok = True
        print(f"  [+] BINGO! CGame = {hex(mul.MANAGER_OFFSET)} (votes {best_manager['votes']}, score={best_manager['struct_score']})")
    else:
        print("  [-] CGame not found")

    # ---------------------------------------------------------
    # 🎯 Phase 2: สแกนหาตัวละครของเรา (DAT_CONTROLLED_UNIT)
    # ---------------------------------------------------------
    print("[*] 🔍 2/5 ค้นหา My Unit (DAT_CONTROLLED)...")
    patterns_hero = ["4C 8B 25 ? ? ? ? 4D 85 E4 74 ? 41 0F B7 44 24 08", "48 8B 05 ? ? ? ? 48 39 C3 74 ? 48 8B 05 ? ? ? ? 80 B8"]
    found_hero_targets = []
    for p in patterns_hero:
        for t in scanner.find_all_patterns(p):
            ghidra_offset = (t - base_address) + 0x400000
            if 0x8000000 < ghidra_offset < 0xC000000:
                found_hero_targets.append(ghidra_offset)
                
    if found_hero_targets:
        top_target, votes = Counter(found_hero_targets).most_common(1)[0]
        print(f"  [+] ✅ BINGO! My Unit = {hex(top_target)} (โหวต {votes} เสียง)")
        mul.DAT_CONTROLLED_UNIT = top_target
        hero_ok = True

    # ---------------------------------------------------------
    # 🎯 Phase 3: สแกนหาโครงสร้างในรถถัง (Struct X และ BBMIN)
    # ---------------------------------------------------------
    print("[*] 🔍 3/5 ค้นหาโครงสร้างตัวถัง (Struct Offsets)...")
    
    # 1️⃣ สแกนหา OFF_UNIT_X (จากคำสั่ง LEA RSI/RDI, [RBX + ?])
    x_patterns = ["48 8D B3 ? ? ? ?", "48 8D BB ? ? ? ?"]
    x_candidates = []
    for p in x_patterns:
        x_candidates.extend(scanner.find_all_struct_offsets(p, offset_index=3))
        
    valid_x = [val for val in x_candidates if 0xA00 <= val <= 0xF00] # พิกัดมักจะอยู่ระหว่าง 0xA00 ถึง 0xF00
    if valid_x:
        top_x, votes = Counter(valid_x).most_common(1)[0]
        print(f"  [+] ✅ BINGO! UNIT_X = {hex(top_x)} (หมุน = {hex(top_x - 0x24)}) (โหวต {votes} เสียง)")
        mul.OFF_UNIT_X = top_x
        mul.OFF_UNIT_ROTATION = top_x - 0x24
    else:
        print("  [-] ❌ หา UNIT_X ไม่เจอ")

    # 2️⃣ สแกนหา OFF_UNIT_BBMIN (จากข้อมูล Ghidra ของท่าน: MOVAPS XMM1, [RBX + ?] หรือ MOVAPS XMM0)
    bbox_patterns = ["0F 28 8B ? ? ? ?", "0F 28 83 ? ? ? ?"]
    bbox_candidates = []
    for p in bbox_patterns:
        bbox_candidates.extend(scanner.find_all_struct_offsets(p, offset_index=3))
        
    valid_bbox = [val for val in bbox_candidates if 0x100 <= val <= 0x300] # BBox มักจะอยู่ระหว่าง 0x100 ถึง 0x300
    if valid_bbox:
        top_bbox, votes = Counter(valid_bbox).most_common(1)[0]
        print(f"  [+] ✅ BINGO! BBMIN = {hex(top_bbox)} (BBMAX = {hex(top_bbox + 0xC)}) (โหวต {votes} เสียง)")
        mul.OFF_UNIT_BBMIN = top_bbox
        mul.OFF_UNIT_BBMAX = top_bbox + 0xC
    else:
        print("  [-] ❌ หา BBMIN ไม่เจอ")

    # ---------------------------------------------------------
    # 🎯 Phase 4: สแกนหาข้อมูลสถานะ (State, Team, Info, Reload)
    # ---------------------------------------------------------
    print("[*] 🔍 4/5 ค้นหา Struct ข้อมูลและสถานะรถถัง (Status Offsets)...")

    # 1️⃣ หา OFF_UNIT_INFO (0xFC0)
    info_patterns = ["48 8B 80 ? ? ? ?", "48 8B 83 ? ? ? ?"]
    info_cands = []
    for p in info_patterns: info_cands.extend(scanner.find_all_struct_offsets(p, 3))
    valid_info = [v for v in info_cands if 0xF00 <= v <= 0x1000]
    if valid_info:
        top_info, votes = Counter(valid_info).most_common(1)[0]
        mul.OFF_UNIT_INFO = top_info
        print(f"  [+] ✅ BINGO! INFO = {hex(top_info)} (โหวต {votes} เสียง)")
    else: print("  [-] ❌ หา INFO ไม่เจอ")

    # 2️⃣ หา OFF_UNIT_TEAM (0xFB0)
    team_patterns = ["0F B6 83 ? ? ? ?", "0F B6 B3 ? ? ? ?", "0F B6 BB ? ? ? ?"]
    team_cands = []
    for p in team_patterns: team_cands.extend(scanner.find_all_struct_offsets(p, 3))
    valid_team = [v for v in team_cands if 0xF00 <= v <= 0x1000]
    if valid_team:
        top_team, votes = Counter(valid_team).most_common(1)[0]
        mul.OFF_UNIT_TEAM = top_team
        print(f"  [+] ✅ BINGO! TEAM = {hex(top_team)} (โหวต {votes} เสียง)")
    else: print("  [-] ❌ หา TEAM ไม่เจอ")

    # 3️⃣ หา OFF_UNIT_STATE (0xF30)
    state_patterns = ["48 8D 93 ? ? ? ?", "48 8D 8B ? ? ? ?"]
    state_cands = []
    for p in state_patterns: state_cands.extend(scanner.find_all_struct_offsets(p, 3))
    valid_state = [v for v in state_cands if 0xE00 <= v <= 0x1000]
    if valid_state:
        top_state, votes = Counter(valid_state).most_common(1)[0]
        mul.OFF_UNIT_STATE = top_state
        print(f"  [+] ✅ BINGO! STATE = {hex(top_state)} (โหวต {votes} เสียง)")
    else: print("  [-] ❌ หา STATE ไม่เจอ")

    # 4️⃣ หา OFF_UNIT_RELOAD (0xAB0)
    reload_patterns = ["48 C7 83 ? ? ? ? 00 00 00 00"]
    reload_cands = []
    for p in reload_patterns: reload_cands.extend(scanner.find_all_struct_offsets(p, 3))
    valid_reload = [v for v in reload_cands if 0x900 <= v <= 0xC00]
    if valid_reload:
        top_reload, votes = Counter(valid_reload).most_common(1)[0]
        mul.OFF_UNIT_RELOAD = top_reload
        # 💡 RELOADING อยู่ก่อนหน้า RELOAD 0x11C bytes เสมอ!
        mul.OFF_UNIT_RELOADING = top_reload - 0x11C
        print(f"  [+] ✅ BINGO! RELOAD = {hex(top_reload)} (RELOADING = {hex(top_reload - 0x11C)}) (โหวต {votes} เสียง)")
    else: print("  [-] ❌ หา RELOAD ไม่เจอ")

    # ---------------------------------------------------------
    # 🎯 Phase 5: ค้นหา View Matrix (0x1C0) - แบบ Persistence
    # ---------------------------------------------------------
    print("[*] 🔍 5/5 ค้นหา Visual System (Triple-Chain DNA)...")
    
    # 🎯 DNA ลายเซ็นต์ดิจิทัลของระบบกล้อง (สกัดจาก Snippet 01642041)
    # บรรทัด 1: 89 8A EC 06 00 00 (MOV [RDX+6EC], ECX)
    # บรรทัด 2: 48 8B 88 70 06 00 00 (MOV RCX, [RAX+670]) <-- เป้าหมาย
    # บรรทัด 3: 0F 11 92 D4 06 00 00 (MOVUPS [RDX+6D4], XMM2)
    visual_dna = "89 8A ?? ?? 00 00 48 8B 88 ?? ?? 00 00 0F 11 92 ?? ?? 00 00"
    
    cam_candidates = scanner.find_visual_dna(visual_dna)
    
    if cam_candidates:
        top_cam = Counter(cam_candidates).most_common(1)[0][0]
        mul.OFF_CAMERA_PTR = top_cam
        print(f"  [+] ✅ DNA MATCH! CAMERA_PTR = {hex(mul.OFF_CAMERA_PTR)}")
    else:
        mul.OFF_CAMERA_PTR = 0x670
        print(f"  [!] ⚠️ DNA ไม่ตรง! ใช้ค่า Persistence: 0x670")
    
    # print("[*] 🔍 5.2/5 ค้นหา Visual System (Persistent Chain)...")
    # 🎯 ใช้ DNA ที่ท่านนายพลสกัดมา: MOV byte ptr [R12+RDX*1 + 1C0], SIL
    # เราจะสแกนหา 0x1C0 และ 0x1E0 ที่อยู่คู่กัน
    dna_pattern = "41 88 B4 14 ?? ?? ?? ?? 41 88 B4 14 ?? ?? ?? ??"
    chains = scanner.find_matrix_chain(dna_pattern)
    
    if chains:
        # เลือกเอาคู่ที่พบบ่อยที่สุด (ปกติจะมีแค่ที่เดียวในฟังก์ชันตั้งค่ากล้อง)
        top_pair = Counter(chains).most_common(1)[0][0]
        mul.OFF_VIEW_MATRIX = top_pair[0] # ตัวแรกคือ 0x1C0
        print(f"  [+] ✅ DNA MATCH! Found Chain: {hex(top_pair[0])} -> {hex(top_pair[1])}")
        print(f"  [+] ✅ BINGO! VIEW_MATRIX = {hex(mul.OFF_VIEW_MATRIX)}")
    else:
        mul.OFF_VIEW_MATRIX = 0x1C0
        print("  [!] ⚠️ Chain Match ล้มเหลว! ใช้ค่า Fallback: 0x1C0")

    # Re-validate DAT_MANAGER using actual visual offsets discovered in phase 5.
    validated_managers = []
    for candidate in manager_candidates:
        raw_cam = scanner.read_mem(candidate["cgame_ptr"] + mul.OFF_CAMERA_PTR, 8)
        if not raw_cam or len(raw_cam) < 8:
            continue
        cam_ptr = struct.unpack("<Q", raw_cam)[0]
        if not mul.is_valid_ptr(cam_ptr):
            continue

        matrix_data = scanner.read_mem(cam_ptr + mul.OFF_VIEW_MATRIX, 64)
        if not _looks_like_view_matrix(matrix_data):
            continue

        validated_managers.append(candidate)

    if validated_managers:
        best_valid = max(validated_managers, key=lambda c: (c["struct_score"], c["votes"]))
        if mul.MANAGER_OFFSET != best_valid["dynamic_offset"]:
            print(
                f"  [+] ✅ REFINED! CGame = {hex(best_valid['dynamic_offset'])} "
                f"(votes {best_valid['votes']}, score={best_valid['struct_score']})"
            )
        else:
            print(
                f"  [+] ✅ VALIDATED! CGame = {hex(best_valid['dynamic_offset'])} "
                f"(votes {best_valid['votes']}, score={best_valid['struct_score']})"
            )
        mul.MANAGER_OFFSET = best_valid["dynamic_offset"]
        manager_ok = True
    else:
        print("  [!] ⚠️ ยังไม่พบ manager candidate ที่อ่าน View Matrix ได้แน่ชัด")

    # Offsets were refreshed; flush per-unit caches to avoid stale class/filter state.
    mul.reset_runtime_caches(clear_view=True)

    print("="*55 + "\n")
    return manager_ok and hero_ok
