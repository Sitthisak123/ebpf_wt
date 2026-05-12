import os
import sys
import re
import math
import struct
import subprocess
import errno
import json
from collections import Counter
import src.utils.mul as mul

# =========================================================
# 🧬 DNA PATTERNS CONFIGURATION (Global)
# =========================================================
# 1️⃣ Core Engine Pointers
PAT_CGAME_MANAGER = ["48 8B 05 ? ? ? ? 48 85 C0", "48 8B 3D ? ? ? ? 48 85 FF"]
PAT_MY_UNIT       = "4C 8B 25 ? ? ? ? 4D 85 E4 74 ? 41 0F B7 44 24 08"

# 2️⃣ Unit Structure (Physical)
PAT_UNIT_X        = ["48 8D B3 ? ? ? ?", "48 8D BB ? ? ? ?"]
PAT_UNIT_BBMIN    = ["0F 28 8B ? ? ? ?", "0F 28 83 ? ? ? ?"]

# 3️⃣ Unit Status & Info
PAT_UNIT_INFO     = ["48 8B 80 ? ? ? ?", "48 8B 83 ? ? ? ?"]
PAT_UNIT_TEAM     = ["0F B6 83 B0 0F 00 00", "0F B6 83 ? ? 00 00"] # DNA: Team (0xFB0)
PAT_UNIT_STATE    = ["83 BB 30 0F 00 00 01", "83 BB ? ? 00 00 01"] # DNA: State (0xF30)
PAT_UNIT_NATION   = "48 63 83 8c 09 00 00" # DNA: Nation (0x98C)
PAT_UNIT_INVUL    = "80 BB 58 0E 00 00 00" # DNA: Invulnerable (0xE58)
PAT_UNIT_RELOAD   = "38 83 ? ? ? ? 74 ? 48 8d bb"

# 4️⃣ Unit Internal Details (Inside Info Struct)
PAT_INFO_CLASS_ID = "48 63 80 90 02 00 00" # DNA: Class ID (0x290)
PAT_INFO_SHORT    = "48 8B 40 28"           # DNA: Short Name (0x28)
PAT_INFO_FAMILY   = "48 8B 40 38"           # DNA: Family (0x38)
PAT_INFO_NAME_KEY = "48 8B 70 40"           # DNA: Name Key (0x40)

# 5️⃣ Physics & Movement (High Precision)
PAT_AIR_VEL       = "0F 10 ? 18 03 00 00 0F 10 ? 24 03 00 00"
PAT_AIR_MOVEMENT  = "8B 7B ? F3 0F 10 8D ? ? FF FF 85 FF 0F 88"
PAT_GROUND_SMART  = "49 8B 84 24 ? ? ? ?"

# 5️⃣ Visual System (View Matrix)
PAT_CAMERA_DNA    = "89 8A ?? ?? 00 00 48 8B 88 ?? ?? 00 00 0F 11 92 ?? ?? 00 00"
PAT_MATRIX_CHAIN  = "41 88 B4 14 ?? ?? ?? ?? 41 88 B4 14 ?? ?? ?? ??"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BBOX_PERSISTENCE_PATH = os.path.join(PROJECT_ROOT, "config", "unit_bbox_persistence.json")
VIEW_MATRIX_PERSISTENCE_PATH = os.path.join(PROJECT_ROOT, "config", "view_matrix_persistence.json")
DEFAULT_GAME_BINARY_PATH = "/home/xda-7/MyGames/WarThunder/linux64/aces"


def _get_binary_fingerprint(binary_path=DEFAULT_GAME_BINARY_PATH):
    try:
        real_path = os.path.realpath(binary_path)
        st = os.stat(real_path)
        return {
            "path": real_path,
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
        }
    except Exception:
        return None


def _fingerprint_matches(doc):
    persisted = doc.get("build_fingerprint") if isinstance(doc, dict) else None
    if not persisted:
        return True
    current = _get_binary_fingerprint()
    if not current:
        return False
    return (
        os.path.realpath(str(persisted.get("path", ""))) == current["path"]
        and int(persisted.get("size", -1)) == current["size"]
        and int(persisted.get("mtime_ns", -1)) == current["mtime_ns"]
    )


def _load_bbox_persistence():
    if not os.path.exists(BBOX_PERSISTENCE_PATH):
        return None
    try:
        with open(BBOX_PERSISTENCE_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if not _fingerprint_matches(doc):
            print("  [!] Persistence warning: bbox ignored due to build fingerprint mismatch")
            return None
        bbmin_off = int(doc.get("bbmin_off", 0) or 0)
        bbmax_off = int(doc.get("bbmax_off", 0) or 0)
        if not (0x100 <= bbmin_off < bbmax_off <= 0x400):
            print("  [!] Persistence warning: bbox ignored due to invalid offset range")
            return None
        return {
            "bbmin_off": bbmin_off,
            "bbmax_off": bbmax_off,
            "source": doc.get("source", "unknown"),
            "updated_by_tool": doc.get("updated_by_tool", "unknown"),
            "confidence": float(doc.get("confidence", 0.0) or 0.0),
        }
    except Exception:
        return None


def _write_view_matrix_persistence(camera_off, matrix_off, source, updated_by_tool, confidence):
    try:
        if not _can_overwrite_persistence(VIEW_MATRIX_PERSISTENCE_PATH, confidence):
            print("  [*] Skip auto-save view persistence: existing confidence is higher")
            return None
        os.makedirs(os.path.dirname(VIEW_MATRIX_PERSISTENCE_PATH), exist_ok=True)
        payload = {
            "updated_at": __import__("datetime").datetime.now().isoformat(),
            "camera_off": int(camera_off),
            "matrix_off": int(matrix_off),
            "source": source,
            "updated_by_tool": updated_by_tool,
            "confidence": float(confidence),
            "build_fingerprint": _get_binary_fingerprint(),
        }
        with open(VIEW_MATRIX_PERSISTENCE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return VIEW_MATRIX_PERSISTENCE_PATH
    except Exception:
        return None


def _needs_bbox_persistence_update(bbmin_off, bbmax_off):
    current = _load_bbox_persistence()
    if not current:
        return True
    return (
        int(current.get("bbmin_off", -1)) != int(bbmin_off)
        or int(current.get("bbmax_off", -1)) != int(bbmax_off)
    )


def _needs_view_persistence_update(camera_off, matrix_off):
    current = _load_view_matrix_persistence()
    if not current:
        return True
    return (
        int(current.get("camera_off", -1)) != int(camera_off)
        or int(current.get("matrix_off", -1)) != int(matrix_off)
    )


def _load_view_matrix_persistence():
    if not os.path.exists(VIEW_MATRIX_PERSISTENCE_PATH):
        return None
    try:
        with open(VIEW_MATRIX_PERSISTENCE_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if not _fingerprint_matches(doc):
            print("  [!] Persistence warning: view matrix ignored due to build fingerprint mismatch")
            return None
        matrix_off_raw = doc.get("matrix_off", 0)
        camera_off_raw = doc.get("camera_off", mul.OFF_CAMERA_PTR)
        matrix_off = int(matrix_off_raw, 16) if isinstance(matrix_off_raw, str) else int(matrix_off_raw or 0)
        camera_off = int(camera_off_raw, 16) if isinstance(camera_off_raw, str) else int(camera_off_raw or mul.OFF_CAMERA_PTR)
        if not (0x100 <= matrix_off <= 0x400):
            print("  [!] Persistence warning: view matrix ignored due to invalid matrix offset")
            return None
        if not (0x100 <= camera_off <= 0x1000):
            print("  [!] Persistence warning: view matrix ignored due to invalid camera offset")
            return None
        return {
            "matrix_off": matrix_off,
            "camera_off": camera_off,
            "source": doc.get("source", "unknown"),
            "updated_by_tool": doc.get("updated_by_tool", "unknown"),
            "confidence": float(doc.get("confidence", 0.0) or 0.0),
        }
    except Exception:
        return None


def _can_overwrite_persistence(path, new_confidence):
    try:
        if not os.path.exists(path):
            return True
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if not _fingerprint_matches(doc):
            return True
        current_confidence = float(doc.get("confidence", 0.0) or 0.0)
        return float(new_confidence) >= current_confidence
    except Exception:
        return True

# ==========================================
# 🛠️ คลาสสำหรับอ่าน Memory & Pattern Scanning
# ==========================================
class MemoryScanner:
    def __init__(self, pid):
        self.pid = pid
        self.closed = False
        self.last_error = ""
        self.mem_fd = -1
        self.mem_fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)

    def read_mem(self, address, size):
        if self.closed:
            self.last_error = "scanner_closed"
            return None
        if address is None or address <= 0x10000:
            return None
        try:
            os.lseek(self.mem_fd, address, os.SEEK_SET)
            return os.read(self.mem_fd, size)
        except OSError as e:
            self.last_error = f"{e.__class__.__name__}: errno={getattr(e, 'errno', '?')} msg={e}"
            # Invalid candidate pointers/offset probes can legitimately fail during scans.
            # Only mark the scanner dead for hard descriptor/process failures.
            if getattr(e, "errno", None) in (errno.ESRCH, errno.EBADF):
                self.close()
            return None
        except Exception as e:
            self.last_error = f"{e.__class__.__name__}: {e}"
            return None

    def is_alive(self):
        if self.closed:
            return False
        try:
            os.kill(self.pid, 0)
            return os.path.exists(f"/proc/{self.pid}/mem")
        except OSError as e:
            self.last_error = f"process_check_failed: errno={getattr(e, 'errno', '?')} msg={e}"
            return False
        except Exception as e:
            self.last_error = f"process_check_exception: {e}"
            return False

    def close(self):
        if self.closed:
            return
        try:
            if isinstance(self.mem_fd, int) and self.mem_fd >= 0:
                os.close(self.mem_fd)
        except Exception:
            pass
        self.closed = True

    def find_all_patterns(self, pattern_hex):
        """ค้นหาลายนิ้วมือหาตัวแปร Global (DAT_MANAGER, MY_UNIT)"""
        regex_bytes = b""
        for chunk in pattern_hex.split():
            if "?" in chunk: # ถ้ามีเครื่องหมาย ? อยู่ในกลุ่มนั้น ไม่ว่าจะ '??' หรือ 'D?' ให้ถือว่าเป็น Wildcard
                regex_bytes += b"."
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
        # ... (เหมือนเดิม) ...
        return self._do_struct_scan(pattern_hex, offset_index)

    def find_offset_with_skip(self, anchor_pattern, target_offset_hex, max_skip=40):
        """
        ค้นหา Offset ปริศนา โดยอิงจาก 'จุดยึด' (Anchor) ที่เรารู้อยู่แล้ว
        รองรับทั้ง 1-byte และ 4-byte offsets ตามมาตรฐาน x86-64
        """
        results = []
        try:
            with open(f"/proc/{self.pid}/maps", "r") as f:
                for line in f:
                    if "aces" in line and "r-xp" in line:
                        parts = line.split()
                        start_addr, end_addr = [int(x, 16) for x in parts[0].split("-")]
                        os.lseek(self.mem_fd, start_addr, os.SEEK_SET)
                        chunk = os.read(self.mem_fd, end_addr - start_addr)
                        
                        target_bytes = struct.pack("<i", target_offset_hex)
                        idx = 0
                        while True:
                            idx = chunk.find(target_bytes, idx + 1)
                            if idx == -1: break
                            
                            # ตรวจสอบว่าข้างหน้าเป็น MOV ยอดนิยมหรือไม่
                            is_mov = False
                            if idx >= 3 and chunk[idx-3] == 0x0F and chunk[idx-2] in [0x10, 0x11, 0x12, 0x28]: is_mov = True
                            elif idx >= 4 and chunk[idx-4] == 0xF3 and chunk[idx-3] == 0x0F: is_mov = True
                            
                            if is_mov:
                                search_start = max(0, idx - max_skip - 7)
                                back_chunk = chunk[search_start : idx]
                                for i in range(len(back_chunk) - 3, -1, -1):
                                    # MOV R, [R + off] โครงสร้าง: [Prefix] [Opcode 8B] [ModR/M] [Offset]
                                    if back_chunk[i] == 0x8B:
                                        prefix = back_chunk[i-1] if i > 0 else 0
                                        if prefix in [0x48, 0x4C, 0x49]:
                                            modrm = back_chunk[i+1]
                                            # ModR/M: 0x40-0x7F = 1-byte offset, 0x80-0xBF = 4-byte offset
                                            if 0x40 <= modrm <= 0x7F:
                                                off = back_chunk[i+2]
                                                results.append(off)
                                                break
                                            elif 0x80 <= modrm <= 0xBF:
                                                if i + 6 < len(back_chunk):
                                                    off = struct.unpack("<i", back_chunk[i+2 : i+6])[0]
                                                    results.append(off)
                                                    break
            return results
        except: return []

    def find_byte_struct_offset(self, pattern_hex, offset_index):
        """ค้นหาลายนิ้วมือโครงสร้าง (อ่าน 1-byte offset)"""
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
                            results.append(mem_dump[match.start() + offset_index])
        except: pass
        return results

    def _do_struct_scan(self, pattern_hex, offset_index):
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
                            struct_offset = struct.unpack("<i", mem_dump[match_offset + offset_index : match_offset + offset_index + 4])[0]
                            results.append(struct_offset)
        except: pass
        return results

    def __del__(self):
        self.close()


def _load_bbox_persistence():
    try:
        if not os.path.exists(BBOX_PERSISTENCE_PATH):
            return None
        with open(BBOX_PERSISTENCE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not _fingerprint_matches(data):
            return None
        bmin_off = int(data.get("bbmin_off", 0) or 0)
        bmax_off = int(data.get("bbmax_off", 0) or 0)
        if 0x100 <= bmin_off <= 0x400 and bmin_off < bmax_off <= 0x400:
            return {
                "bbmin_off": bmin_off,
                "bbmax_off": bmax_off,
                "source": data.get("source") or "persisted",
                "updated_by_tool": data.get("updated_by_tool", "unknown"),
                "confidence": float(data.get("confidence", 0.0) or 0.0),
            }
    except Exception:
        return None
    return None


def _write_bbox_persistence(bbmin_off, bbmax_off, source, updated_by_tool, confidence):
    try:
        if not _can_overwrite_persistence(BBOX_PERSISTENCE_PATH, confidence):
            print("  [*] Skip auto-save bbox persistence: existing confidence is higher")
            return None
        os.makedirs(os.path.dirname(BBOX_PERSISTENCE_PATH), exist_ok=True)
        payload = {
            "updated_at": __import__("datetime").datetime.now().isoformat(),
            "bbmin_off": int(bbmin_off),
            "bbmax_off": int(bbmax_off),
            "source": source,
            "updated_by_tool": updated_by_tool,
            "confidence": float(confidence),
            "build_fingerprint": _get_binary_fingerprint(),
        }
        with open(BBOX_PERSISTENCE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return BBOX_PERSISTENCE_PATH
    except Exception:
        return None


def _read_vec3(scanner, base_ptr, offset):
    raw = scanner.read_mem(base_ptr + offset, 12)
    if not raw or len(raw) < 12:
        return None
    vals = struct.unpack("<fff", raw)
    if not all(math.isfinite(v) for v in vals):
        return None
    if any(abs(v) > 10000.0 for v in vals):
        return None
    return vals


def _valid_bbox_pair(bmin, bmax):
    if not bmin or not bmax:
        return False
    dx = bmax[0] - bmin[0]
    dy = bmax[1] - bmin[1]
    dz = bmax[2] - bmin[2]
    return 0.5 < dx < 100.0 and 0.2 < dy < 40.0 and 0.5 < dz < 100.0


def _score_bbox_pair(scanner, cgame_ptr, bbmin_off, bbmax_off, max_units=24):
    if not mul.is_valid_ptr(cgame_ptr):
        return -9999.0, 0
    units = mul.get_all_units(scanner, cgame_ptr)
    if not units:
        return -9999.0, 0
    valid_rows = []
    for u_ptr, _ in units[:max_units]:
        bmin = _read_vec3(scanner, u_ptr, bbmin_off)
        bmax = _read_vec3(scanner, u_ptr, bbmax_off)
        if not _valid_bbox_pair(bmin, bmax):
            continue
        dims = (bmax[0] - bmin[0], bmax[1] - bmin[1], bmax[2] - bmin[2])
        valid_rows.append(dims)
    if not valid_rows:
        return -9999.0, 0
    avg_dx = sum(v[0] for v in valid_rows) / len(valid_rows)
    avg_dy = sum(v[1] for v in valid_rows) / len(valid_rows)
    avg_dz = sum(v[2] for v in valid_rows) / len(valid_rows)
    score = len(valid_rows) * 10.0
    score -= abs(avg_dy - 2.0) * 2.0
    score -= abs(avg_dx - 3.5) * 1.0
    score -= abs(avg_dz - 5.0) * 1.0
    return score, len(valid_rows)


def _refine_bbox_offsets(scanner, base_address, top_bbox=None):
    persisted = _load_bbox_persistence()
    cgame_ptr = mul.get_cgame_base(scanner, base_address)
    candidates = set()
    if persisted:
        candidates.add((persisted["bbmin_off"], persisted["bbmax_off"], "persisted"))
    if top_bbox:
        for delta in (0x0C, 0x10, 0x14, 0x18, 0x20):
            candidates.add((top_bbox, top_bbox + delta, "pattern"))
    for bmin_off in range(0x1B0, 0x251, 0x10):
        for delta in (0x0C, 0x10, 0x14, 0x18, 0x20):
            candidates.add((bmin_off, bmin_off + delta, "sweep"))
    for bmin_off in range(0x1D0, 0x241, 0x04):
        for delta in (0x0C, 0x10, 0x14, 0x18, 0x20):
            candidates.add((bmin_off, bmin_off + delta, "sweep"))

    best = None
    for bbmin_off, bbmax_off, source in sorted(candidates):
        if not (0x100 <= bbmin_off < bbmax_off <= 0x400):
            continue
        score, valid_count = _score_bbox_pair(scanner, cgame_ptr, bbmin_off, bbmax_off)
        if best is None or (score, valid_count) > (best["score"], best["valid_count"]):
            best = {
                "bbmin_off": bbmin_off,
                "bbmax_off": bbmax_off,
                "score": score,
                "valid_count": valid_count,
                "source": source,
            }
    return best

def get_game_pid():
    try:
        pid_str = subprocess.check_output(["pgrep", "aces"]).decode().strip().split('\n')[0]
        return int(pid_str)
    except Exception as e:
        raise RuntimeError(
            "ไม่พบ process ของเกม 'aces' กรุณาเปิดเกมก่อนแล้วค่อยรัน overlay"
        ) from e

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

def _handle_fallback(name, current_val):
    if current_val == 0:
        print(f"  [!] ❌ CRITICAL: สแกนหา {name} ไม่สำเร็จ และไม่มีค่า Persistence (0) -> ต้องปิดโปรแกรม")
        import sys
        sys.exit(1)
    print(f"  [!] ⚠️ หา {name} ไม่เจอ ใช้ค่า Persistence: {hex(current_val)}")
    return current_val

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
    all_manager_targets = []
    manager_candidates = []
    for p in PAT_CGAME_MANAGER:
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

            live_score, live_units = mul._score_cgame_live(scanner, cgame_ptr)

            manager_candidates.append({
                "target_addr": target_addr,
                "dynamic_offset": target_addr - base_address,
                "votes": count,
                "cgame_ptr": cgame_ptr,
                "struct_score": struct_score,
                "live_score": live_score,
                "live_units": live_units,
            })

    if manager_candidates:
        best_manager = max(manager_candidates, key=lambda c: (c["live_units"], c["votes"]))
        mul.MANAGER_OFFSET = best_manager["dynamic_offset"]
        manager_ok = True
        print(f"  [+] BINGO! CGame = {hex(mul.MANAGER_OFFSET)} (live={best_manager['live_units']})")
    else:
        mul.MANAGER_OFFSET = _handle_fallback("CGame Base", mul.MANAGER_OFFSET)
        manager_ok = True

    # ---------------------------------------------------------
    # 🎯 Phase 2: ค้นหา My Unit (DAT_CONTROLLED)
    # ---------------------------------------------------------
    print("[*] 🔍 2/5 ค้นหา My Unit (DAT_CONTROLLED)...")
    found_hero = scanner.find_all_patterns(PAT_MY_UNIT)
    if found_hero:
        top_target = Counter(found_hero).most_common(1)[0][0]
        mul.DAT_CONTROLLED_UNIT = (top_target - base_address) + 0x400000
        hero_ok = True
        print(f"  [+] ✅ BINGO! My Unit = {hex(mul.DAT_CONTROLLED_UNIT)}")
    else:
        mul.DAT_CONTROLLED_UNIT = _handle_fallback("My Unit", mul.DAT_CONTROLLED_UNIT)
        hero_ok = True

    # ---------------------------------------------------------
    # 🎯 Phase 3: สแกนหาโครงสร้างในรถถัง (Struct X และ BBMIN)
    # ---------------------------------------------------------
    print("[*] 🔍 3/5 ค้นหาโครงสร้างตัวถัง (Struct Offsets)...")
    
    # 1️⃣ สแกนหา OFF_UNIT_X
    x_cands = []
    for p in PAT_UNIT_X: x_cands.extend(scanner.find_all_struct_offsets(p, 3))
    valid_x = [v for v in x_cands if 0xA00 <= v <= 0xF00]
    if valid_x:
        top_x = Counter(valid_x).most_common(1)[0][0]
        mul.OFF_UNIT_X, mul.OFF_UNIT_ROTATION = top_x, top_x - 0x24
        print(f"  [+] ✅ BINGO! UNIT_X = {hex(top_x)}")
    else:
        mul.OFF_UNIT_X = _handle_fallback("UNIT_X", mul.OFF_UNIT_X)
        mul.OFF_UNIT_ROTATION = mul.OFF_UNIT_X - 0x24

    # 2️⃣ Bounding Box persistence ที่ยืนยันจาก dumper/debugger จะ override scanner vote
    bbox_persistence = _load_bbox_persistence()
    if bbox_persistence:
        mul.OFF_UNIT_BBMIN = bbox_persistence["bbmin_off"]
        mul.OFF_UNIT_BBMAX = bbox_persistence["bbmax_off"]
        print(
            f"  [+] ✅ OVERRIDE! BBMIN = {hex(mul.OFF_UNIT_BBMIN)} "
            f"BBMAX = {hex(mul.OFF_UNIT_BBMAX)} (persistence:{bbox_persistence['source']}"
            f" tool:{bbox_persistence['updated_by_tool']} conf:{bbox_persistence['confidence']:.2f})"
        )
    else:
        mul.OFF_UNIT_BBMIN = 0x0238
        mul.OFF_UNIT_BBMAX = 0x0244
        print("  [!] Persistence warning: bbox fallback is active")
        print(f"  [+] 📦 FALLBACK BBOX! BBMIN = {hex(mul.OFF_UNIT_BBMIN)}")
        print(f"  [+] 📦 FALLBACK BBOX! BBMAX = {hex(mul.OFF_UNIT_BBMAX)}")
    if _needs_bbox_persistence_update(mul.OFF_UNIT_BBMIN, mul.OFF_UNIT_BBMAX):
        saved = _write_bbox_persistence(
            mul.OFF_UNIT_BBMIN,
            mul.OFF_UNIT_BBMAX,
            "scanner_auto_bbox",
            "scanner",
            0.72,
        )
        if saved:
            print(
                f"  [+] 💾 AUTO-SAVED! BBMIN = {hex(mul.OFF_UNIT_BBMIN)} "
                f"BBMAX = {hex(mul.OFF_UNIT_BBMAX)}"
            )

    # ---------------------------------------------------------
    # 🎯 Phase 4: สแกนหาข้อมูลสถานะ (State, Team, Info, Reload)
    # ---------------------------------------------------------
    print("[*] 🔍 4/5 ค้นหา Struct ข้อมูลและสถานะรถถัง (Status Offsets)...")

    # 1️⃣ หา OFF_UNIT_INFO
    info_cands = []
    for p in PAT_UNIT_INFO: info_cands.extend(scanner.find_all_struct_offsets(p, 3))
    valid_info = [v for v in info_cands if 0xF00 <= v <= 0x1000]
    if valid_info:
        top_info, votes = Counter(valid_info).most_common(1)[0]
        mul.OFF_UNIT_INFO = top_info
        print(f"  [+] ✅ BINGO! INFO = {hex(top_info)} (โหวต {votes} เสียง)")
    else: print("  [-] ❌ หา INFO ไม่เจอ")

    # 2️⃣ หา OFF_UNIT_TEAM
    team_cands = []
    for p in PAT_UNIT_TEAM: team_cands.extend(scanner.find_all_struct_offsets(p, 3))
    valid_team = [v for v in team_cands if 0xF00 <= v <= 0x1000]
    if valid_team:
        top_team, votes = Counter(valid_team).most_common(1)[0]
        mul.OFF_UNIT_TEAM = top_team
        print(f"  [+] ✅ BINGO! TEAM = {hex(top_team)} (โหวต {votes} เสียง)")
    else: print("  [-] ❌ หา TEAM ไม่เจอ")

    # 3️⃣ หา OFF_UNIT_STATE
    state_cands = []
    for p in PAT_UNIT_STATE: state_cands.extend(scanner.find_all_struct_offsets(p, 2))
    valid_state = [v for v in state_cands if 0xF00 <= v <= 0x1000]
    if valid_state:
        top_state, votes = Counter(valid_state).most_common(1)[0]
        mul.OFF_UNIT_STATE = top_state
        print(f"  [+] ✅ BINGO! STATE = {hex(top_state)} (โหวต {votes} เสียง)")
    else: print("  [-] ❌ หา STATE ไม่เจอ")

    # 4️⃣ หา OFF_UNIT_RELOAD
    reload_cands = scanner.find_all_struct_offsets(PAT_UNIT_RELOAD, 2)
    valid_reload = [v for v in reload_cands if 0x900 <= v <= 0xC00]
    if valid_reload:
        top_reload, votes = Counter(valid_reload).most_common(1)[0]
        mul.OFF_UNIT_RELOAD = top_reload
        mul.OFF_UNIT_RELOADING = top_reload - 0x11C
        print(f"  [+] ✅ BINGO! RELOAD = {hex(top_reload)} (RELOADING = {hex(top_reload - 0x11C)}) (โหวต {votes} เสียง)")
    else: print("  [-] ❌ หา RELOAD ไม่เจอ")

    # 5️⃣ หา OFF_AIR_VEL (0x318)
    # 🧬 DNA: 0F 10 ?? 18 03 00 00 0F 10 ?? 24 03 00 00 (จาก 025effcb)
    # air_vel_dna = "0F 10 ? 18 03 00 00 0F 10 ? 24 03 00 00"
    # air_vel_cands = scanner.find_all_struct_offsets(air_vel_dna, 3)
    # if air_vel_cands:
    #     top_vel = Counter(air_vel_cands).most_common(1)[0][0]
    #     mul.OFF_AIR_VEL = top_vel
    #     print(f"  [+] ✅ BINGO! AIR_VEL = {hex(mul.OFF_AIR_VEL)} (โหวต {Counter(air_vel_cands).most_common(1)[0][1]} เสียง)")
    # else:
    #     print(f"  [!] ⚠️ หา AIR_VEL ไม่เจอ ใช้ค่า Persistence: {hex(mul.OFF_AIR_VEL)}")

    # 6️⃣ หา OFF_AIR_MOVEMENT (0x18) - 🆕 High Precision (Byte)
    # DNA จาก LAB_017e1919: MOV RDI, [RDX + 0xd18] -> MOV [RBP+var], RDX -> MOV [RBP+var], RSI -> MOV RAX, [RDI]
    air_mov_dna = "48 8B BA ?? ?? ?? ?? 48 89 55 ?? 48 89 75 ?? 48 8B 07"
    # 🎯 สแกนหา 4 ไบต์ (18 0D 00 00) โดยเริ่มอ่านที่ Index 3
    air_mov_cands = scanner.find_all_struct_offsets(air_mov_dna, 3)
    if air_mov_cands:
        top_mov, votes = Counter(air_mov_cands).most_common(1)[0]
        mul.OFF_AIR_MOVEMENT = top_mov
        print(f"  [+] ✅ BINGO! AIR_MOVEMENT = {hex(mul.OFF_AIR_MOVEMENT)} (โหวต {votes} เสียง)")
    else:
        print(f"  [!] ⚠️ หา AIR_MOVEMENT ไม่เจอ ใช้ค่า Persistence: {hex(mul.OFF_AIR_MOVEMENT)}")

    # 7️⃣ หา OFF_GROUND_SMART (0x1DF8) - 🆕 High Precision (49 8B 84 24)
    # 🧬 DNA: 49 8B 84 24 F8 1D 00 00 (จาก FUN_00ad6b20)
    ground_smart_dna = "49 8B 84 24 ? ? ? ?"
    smart_cands = scanner.find_all_struct_offsets(ground_smart_dna, 4)
    if smart_cands:
        valid_smart = [v for v in smart_cands if 0x1D00 <= v <= 0x1F00]
        if valid_smart:
            top_smart, votes = Counter(valid_smart).most_common(1)[0]
            mul.OFF_GROUND_MOVEMENT = top_smart
            print(f"  [+] ✅ BINGO! GROUND_SMART = {hex(top_smart)} (โหวต {votes} เสียง)")
    else:
        print(f"  [!] ⚠️ หา GROUND_SMART ไม่เจอ ใช้ค่า Persistence: 0x1df8")

    # ---------------------------------------------------------
    # 🎯 Phase 8: ค้นหา View Matrix (0x1C0) - แบบ Persistence
    # ---------------------------------------------------------
    print("[*] 🔍 8/8 ค้นหา Visual System (Triple-Chain DNA)...")
    
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
        mul.OFF_VIEW_MATRIX = 0x1D0 # ตัวแรกคือ 0x1C0
        print(f"  [+] ✅ DNA MATCH! Found Chain: {hex(top_pair[0])} -> {hex(top_pair[1])}")
        print(f"  [+] ✅ BINGO! VIEW_MATRIX = {hex(mul.OFF_VIEW_MATRIX)}")
    else:
        mul.OFF_VIEW_MATRIX = 0x1C0
        print("  [!] Persistence warning: view matrix scanner fell back to default offset")
        print("  [!] ⚠️ Chain Match ล้มเหลว! ใช้ค่า Fallback: 0x1C0")

    view_persistence = _load_view_matrix_persistence()
    if view_persistence:
        mul.OFF_CAMERA_PTR = view_persistence["camera_off"]
        mul.OFF_VIEW_MATRIX = view_persistence["matrix_off"]
        print(
            f"  [+] ✅ OVERRIDE! CAMERA_PTR = {hex(mul.OFF_CAMERA_PTR)} "
            f"VIEW_MATRIX = {hex(mul.OFF_VIEW_MATRIX)} (persistence:{view_persistence['source']}"
            f" tool:{view_persistence['updated_by_tool']} conf:{view_persistence['confidence']:.2f})"
        )
    if _needs_view_persistence_update(mul.OFF_CAMERA_PTR, mul.OFF_VIEW_MATRIX):
        saved = _write_view_matrix_persistence(
            mul.OFF_CAMERA_PTR,
            mul.OFF_VIEW_MATRIX,
            "scanner_auto_view_matrix",
            "scanner",
            0.78,
        )
        if saved:
            print(
                f"  [+] 💾 AUTO-SAVED! CAMERA_PTR = {hex(mul.OFF_CAMERA_PTR)} "
                f"VIEW_MATRIX = {hex(mul.OFF_VIEW_MATRIX)}"
            )

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
        def _manager_rank(c):
            return (
                1 if c["live_units"] > 0 else 0,
                c["live_score"],
                c["struct_score"],
                c["votes"],
            )

        best_valid = max(validated_managers, key=_manager_rank)
        current_choice = next((c for c in manager_candidates if c["dynamic_offset"] == mul.MANAGER_OFFSET), None)

        if current_choice and current_choice["live_units"] > 0 and best_valid["live_units"] == 0:
            print(
                f"  [+] ✅ KEEP CGame = {hex(current_choice['dynamic_offset'])} "
                f"(live={current_choice['live_units']}) | reject refined live=0"
            )
        else:
            if mul.MANAGER_OFFSET != best_valid["dynamic_offset"]:
                print(
                    f"  [+] ✅ REFINED! CGame = {hex(best_valid['dynamic_offset'])} "
                    f"(votes {best_valid['votes']}, score={best_valid['struct_score']}, live={best_valid['live_units']})"
                )
            else:
                print(
                    f"  [+] ✅ VALIDATED! CGame = {hex(best_valid['dynamic_offset'])} "
                    f"(votes {best_valid['votes']}, score={best_valid['struct_score']}, live={best_valid['live_units']})"
                )
            mul.MANAGER_OFFSET = best_valid["dynamic_offset"]
            manager_ok = True
    else:
        print("  [!] ⚠️ ยังไม่พบ manager candidate ที่อ่าน View Matrix ได้แน่ชัด")

    # Offsets were refreshed; flush per-unit caches to avoid stale class/filter state.
    mul.reset_runtime_caches(clear_view=True)

    print("="*55 + "\n")
    return manager_ok and hero_ok
