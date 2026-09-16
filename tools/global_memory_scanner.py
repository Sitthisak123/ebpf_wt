#!/usr/bin/env python3
"""
===============================================================================
Global Memory Scanner (Cheat Engine style CLI) for Linux / War Thunder
===============================================================================
เครื่องมือสแกนหน่วยความจำระดับ Global สไตล์ Cheat Engine สำหรับ Linux:
- ค้นหาค่าตัวเลข (First Scan / Next Scan) ด้วยความเร็วสูงระดับ SIMD ผ่าน NumPy
- กรองค่า: Exact Value, Decreased Value, Increased Value, Changed, Unchanged
- แสดงผล Offset สัมพันธ์กับ my_unit ([my_unit + 0xXXXX]) และ Binary (aces) อัตโนมัติ
- โหมด Live Watch มอนิเตอร์ค่า Real-time แบบไฮไลต์สีเมื่อค่าเปลี่ยนแปลง
- รองรับ Undo Scan ย้อนกลับประวัติการกรองได้
- สแกนหา Pointer Path / Xrefs ไปยังแอดเดรสเป้าหมาย
- รองรับชนิดข้อมูล: i32 (default), u32, i16, u16, i64, u64, f32, f64, i8, u8
===============================================================================
"""

import os
import sys
import time
import struct
import signal
import argparse
import readline
import select
from typing import List, Tuple, Optional, Dict, Any

try:
    import numpy as np
except ImportError:
    print("[-] Error: 'numpy' is required for high-speed scanning. Run: pip install numpy")
    sys.exit(1)

# นำเข้า Scanner เดิมของโปรเจกต์หากมี เพื่อดึง DNA my_unit
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from src.utils.scanner import MemoryScanner, PAT_MY_UNIT
    HAS_EBPF_SCANNER = True
except Exception:
    HAS_EBPF_SCANNER = False

# ANSI Color Codes
COLOR_RESET   = "\033[0m"
COLOR_BOLD    = "\033[1m"
COLOR_RED     = "\033[91m"
COLOR_GREEN   = "\033[92m"
COLOR_YELLOW  = "\033[93m"
COLOR_BLUE    = "\033[94m"
COLOR_MAGENTA = "\033[95m"
COLOR_CYAN    = "\033[96m"
COLOR_GRAY    = "\033[90m"
COLOR_BG_DARK = "\033[40m"


TYPE_CONFIG = {
    "i32": {"dtype": np.int32,   "size": 4, "format": "<i", "name": "4-byte Signed (int32)"},
    "u32": {"dtype": np.uint32,  "size": 4, "format": "<I", "name": "4-byte Unsigned (uint32)"},
    "i16": {"dtype": np.int16,   "size": 2, "format": "<h", "name": "2-byte Signed (int16)"},
    "u16": {"dtype": np.uint16,  "size": 2, "format": "<H", "name": "2-byte Unsigned (uint16)"},
    "i64": {"dtype": np.int64,   "size": 8, "format": "<q", "name": "8-byte Signed (int64)"},
    "u64": {"dtype": np.uint64,  "size": 8, "format": "<Q", "name": "8-byte Unsigned (uint64)"},
    "f32": {"dtype": np.float32, "size": 4, "format": "<f", "name": "Float (single)"},
    "f64": {"dtype": np.float64, "size": 8, "format": "<d", "name": "Double"},
    "i8":  {"dtype": np.int8,    "size": 1, "format": "<b", "name": "1-byte Signed (int8)"},
    "u8":  {"dtype": np.uint8,   "size": 1, "format": "<B", "name": "1-byte Unsigned (uint8)"},
}


class MemoryRegion:
    __slots__ = ('start', 'end', 'size', 'perms', 'pathname')
    def __init__(self, start: int, end: int, perms: str, pathname: str):
        self.start = start
        self.end = end
        self.size = end - start
        self.perms = perms
        self.pathname = pathname


class GlobalMemoryScanner:
    def __init__(self, pid: int, data_type: str = "i32", scope: str = "heap"):
        self.pid = pid
        self.mem_fd = -1
        self.data_type = data_type if data_type in TYPE_CONFIG else "i32"
        self.scope = scope  # 'heap', 'anon', 'rw', 'unit', 'all'
        self.regions: List[MemoryRegion] = []
        self.candidates: List[Tuple[int, Any]] = [] # list of (addr, current_value)
        self.history: List[Tuple[List[Tuple[int, Any]], str]] = [] # undo stack
        self.my_unit: int = 0
        self.binary_base: int = 0
        self.binary_name: str = ""
        self.process_name: str = ""
        self.alignment: int = TYPE_CONFIG[self.data_type]["size"]
        self.chunk_size = 16 * 1024 * 1024 # 16 MB chunk size for high responsiveness
        self.airstate_base: int = 0

    def open_process(self) -> bool:
        """เปิดไฟล์ /proc/<pid>/mem และโหลดตาราง Memory Maps"""
        try:
            with open(f"/proc/{self.pid}/comm", "r") as f:
                self.process_name = f.read().strip()
        except Exception:
            self.process_name = f"PID {self.pid}"

        mem_path = f"/proc/{self.pid}/mem"
        try:
            self.mem_fd = os.open(mem_path, os.O_RDWR)
        except PermissionError:
            try:
                self.mem_fd = os.open(mem_path, os.O_RDONLY)
                print(f"{COLOR_YELLOW}[!] Opened /proc/{self.pid}/mem in READ-ONLY mode.{COLOR_RESET}")
            except Exception as e:
                print(f"{COLOR_RED}[-] Cannot open {mem_path}: {e}{COLOR_RESET}")
                print(f"{COLOR_YELLOW}[!] Hint: Run with sudo! (e.g. echo [pwd] | sudo -S ...){COLOR_RESET}")
                return False
        except Exception as e:
            print(f"{COLOR_RED}[-] Cannot open {mem_path}: {e}{COLOR_RESET}")
            return False

        self.refresh_maps()
        self.detect_game_pointers()
        return True

    def close(self):
        if self.mem_fd >= 0:
            try:
                os.close(self.mem_fd)
            except Exception:
                pass
            self.mem_fd = -1

    def refresh_maps(self):
        """อ่านข้อมูล Virtual Memory Maps ของโปรเซส"""
        self.regions.clear()
        try:
            with open(f"/proc/{self.pid}/maps", "r") as f:
                for line in f:
                    parts = line.strip().split(maxsplit=5)
                    if len(parts) < 5:
                        continue
                    addr_range, perms = parts[0], parts[1]
                    pathname = parts[5] if len(parts) >= 6 else "[anon]"
                    start_str, end_str = addr_range.split("-")
                    start_addr = int(start_str, 16)
                    end_addr = int(end_str, 16)

                    # บันทึก Base Address ของ Binary หลัก
                    if not self.binary_base and "r-xp" in perms and ("aces" in pathname or self.process_name in pathname):
                        self.binary_base = start_addr
                        self.binary_name = os.path.basename(pathname)

                    self.regions.append(MemoryRegion(start_addr, end_addr, perms, pathname))
        except Exception as e:
            print(f"{COLOR_RED}[-] Error reading /proc/{self.pid}/maps: {e}{COLOR_RESET}")

    def detect_game_pointers(self):
        """ตรวจหา my_unit และ AirState table โดยอัตโนมัติหากเป็น War Thunder (aces)"""
        if "aces" not in self.process_name.lower():
            return

        if HAS_EBPF_SCANNER:
            try:
                scanner = MemoryScanner(self.pid)
                ptrs = scanner.find_all_patterns(PAT_MY_UNIT)
                if ptrs:
                    raw = scanner.read_mem(ptrs[0], 8)
                    if raw and len(raw) == 8:
                        u = struct.unpack("<Q", raw)[0]
                        if 0x10000 < u < 0x7fffffffffff:
                            self.my_unit = u
                            print(f"{COLOR_GREEN}[+] Detected War Thunder player my_unit: 0x{self.my_unit:08x}{COLOR_RESET}")
                            
                            # ตรวจจับ AirState HUD table ที่ my_unit + 0x31ea0
                            raw_sq = scanner.read_mem(self.my_unit + 0x31ea0, 8)
                            if raw_sq and len(raw_sq) == 8:
                                sq = struct.unpack("<Q", raw_sq)[0]
                                if 0x10000 < sq < 0x7fffffffffff:
                                    self.airstate_base = sq
                                    print(f"{COLOR_MAGENTA}[+] Detected AirState / HUD Table: 0x{self.airstate_base:08x}{COLOR_RESET}")
            except Exception as e:
                pass

    def read_single_value(self, addr: int) -> Optional[Any]:
        """อ่านค่า 1 ค่าที่แอดเดรสตาม type ปัจจุบัน"""
        cfg = TYPE_CONFIG[self.data_type]
        sz = cfg["size"]
        fmt = cfg["format"]
        try:
            raw = os.pread(self.mem_fd, sz, addr)
            if len(raw) == sz:
                val = struct.unpack(fmt, raw)[0]
                if self.data_type in ("f32", "f64"):
                    return round(float(val), 4)
                return val
        except Exception:
            pass
        return None

    def get_scoped_regions(self) -> List[MemoryRegion]:
        """คัดกรอง Region ตาม Scope ที่เลือก"""
        matched = []
        for r in self.regions:
            # ต้องเป็น Readable
            if not ("r" in r.perms):
                continue

            if self.scope == "heap":
                if r.pathname == "[heap]" and "w" in r.perms:
                    matched.append(r)
            elif self.scope == "unit":
                if self.my_unit > 0:
                    unit_start = (self.my_unit - 0x1000) & ~0xFFF
                    unit_end = (self.my_unit + 0x30000 + 0xFFF) & ~0xFFF
                    ov_start = max(r.start, unit_start)
                    ov_end = min(r.end, unit_end)
                    if ov_start < ov_end:
                        matched.append(MemoryRegion(ov_start, ov_end, r.perms, f"{r.pathname} [unit]"))
                else:
                    # ถ้าไม่มี my_unit ให้ fallback เป็น heap
                    if r.pathname == "[heap]" and "w" in r.perms:
                        matched.append(r)
            elif self.scope == "anon":
                if "w" in r.perms and (r.pathname == "[anon]" or r.pathname == "[heap]" or r.pathname == "[stack]"):
                    # ข้าม mapping ขนาดมหาศาลที่อาจเป็น GPU Shared Buffer (>512MB)
                    if r.size <= 512 * 1024 * 1024:
                        matched.append(r)
            elif self.scope == "rw":
                if "w" in r.perms:
                    matched.append(r)
            elif self.scope == "module":
                if self.binary_name and self.binary_name in r.pathname and "w" in r.perms:
                    matched.append(r)
            elif self.scope in ("air", "airstate"):
                if getattr(self, 'airstate_base', 0) > 0:
                    as_start = self.airstate_base & ~0xFFF
                    as_end = (self.airstate_base + 0x4000 + 0xFFF) & ~0xFFF
                    ov_start = max(r.start, as_start)
                    ov_end = min(r.end, as_end)
                    if ov_start < ov_end:
                        matched.append(MemoryRegion(ov_start, ov_end, r.perms, f"{r.pathname} [airState]"))
            elif self.scope == "all":
                matched.append(r)

        return matched

    def first_scan(self, target_val: Any, val_max: Optional[Any] = None) -> int:
        """First Scan: สแกนหาค่าเริ่มต้นจากทุก Region ใน Scope (รองรับค่าเดี่ยว หรือช่วงระหว่าง min..max)"""
        cfg = TYPE_CONFIG[self.data_type]
        dtype = cfg["dtype"]
        val_sz = cfg["size"]
        align = self.alignment
        is_range = (val_max is not None)

        scoped_regions = self.get_scoped_regions()
        total_bytes = sum(r.size for r in scoped_regions)
        scan_label = f"between {target_val} and {val_max}" if is_range else str(target_val)
        print(f"{COLOR_CYAN}[*] First Scan for {COLOR_BOLD}{scan_label}{COLOR_RESET}{COLOR_CYAN} ({cfg['name']}, align={align}) across {len(scoped_regions)} regions ({total_bytes / (1024*1024):.2f} MB)...{COLOR_RESET}")

        t0 = time.time()
        new_matches: List[Tuple[int, Any]] = []

        is_float = self.data_type in ("f32", "f64")
        target_f = float(target_val) if is_float else 0
        max_f = float(val_max) if is_range and is_float else 0

        for r_idx, reg in enumerate(scoped_regions):
            cur = reg.start
            # ปรับให้ตรงตาม alignment
            rem = cur % align
            if rem != 0:
                cur += (align - rem)

            while cur < reg.end:
                sz = min(self.chunk_size, reg.end - cur)
                # ปัดเศษขนาดก้อนให้เป็นพหุคูณของ val_sz
                usable_sz = sz - (sz % val_sz)
                if usable_sz < val_sz:
                    break

                try:
                    data = os.pread(self.mem_fd, usable_sz, cur)
                    if len(data) >= val_sz:
                        arr = np.frombuffer(data[:len(data) - (len(data) % val_sz)], dtype=dtype)
                        if is_range:
                            if is_float:
                                idxs = np.nonzero((arr >= target_f) & (arr <= max_f))[0]
                            else:
                                idxs = np.nonzero((arr >= target_val) & (arr <= val_max))[0]
                        else:
                            if is_float:
                                # ตรวจสอบ float ด้วย tolerance 0.01
                                idxs = np.nonzero(np.isclose(arr, target_f, atol=0.01, rtol=1e-4))[0]
                            else:
                                idxs = np.nonzero(arr == target_val)[0]

                        for idx in idxs:
                            match_addr = cur + int(idx) * val_sz
                            # บันทึก (address, value)
                            found_v = arr[idx]
                            new_matches.append((match_addr, float(found_v) if is_float else int(found_v)))
                except Exception:
                    pass

                cur += usable_sz

        elapsed = time.time() - t0
        self.history.append((list(self.candidates), f"First Scan: {scan_label}"))
        self.candidates = new_matches

        print(f"{COLOR_GREEN}[+] First Scan complete in {elapsed:.3f}s. Found {COLOR_BOLD}{len(new_matches):,}{COLOR_RESET}{COLOR_GREEN} matches.{COLOR_RESET}")
        self.print_candidates(limit=20)
        return len(new_matches)

    def next_scan(self, op: str = "exact", target_val: Any = None, delta: Optional[Any] = None, val_max: Optional[Any] = None) -> int:
        """
        Next Scan: กรอง candidate ที่มีอยู่เดิม
        op: 'exact', 'decreased', 'increased', 'changed', 'unchanged', 'between'
        """
        if not self.candidates:
            print(f"{COLOR_YELLOW}[!] Candidate list is empty. Run 'scan <val>' first.{COLOR_RESET}")
            return 0

        cfg = TYPE_CONFIG[self.data_type]
        is_float = self.data_type in ("f32", "f64")

        desc = f"Next Scan: {op}"
        if op == "between":
            desc += f" {target_val}..{val_max}"
        elif target_val is not None:
            desc += f" {target_val}"
        elif delta is not None:
            desc += f" by {delta}"

        print(f"{COLOR_CYAN}[*] Filtering {len(self.candidates):,} candidates with condition: {COLOR_BOLD}{desc}{COLOR_RESET}...")

        t0 = time.time()
        new_matches: List[Tuple[int, Any]] = []

        for addr, prev_val in self.candidates:
            cur_val = self.read_single_value(addr)
            if cur_val is None:
                continue

            keep = False
            if op == "exact":
                if is_float:
                    keep = abs(cur_val - float(target_val)) < 0.01
                else:
                    keep = (cur_val == target_val)
            elif op == "between":
                if is_float:
                    keep = (float(target_val) <= cur_val <= float(val_max))
                else:
                    keep = (target_val <= cur_val <= val_max)
            elif op == "decreased":
                if delta is not None:
                    keep = (cur_val == prev_val - delta)
                else:
                    keep = (cur_val < prev_val)
            elif op == "increased":
                if delta is not None:
                    keep = (cur_val == prev_val + delta)
                else:
                    keep = (cur_val > prev_val)
            elif op == "changed":
                if is_float:
                    keep = abs(cur_val - prev_val) > 1e-4
                else:
                    keep = (cur_val != prev_val)
            elif op == "unchanged":
                if is_float:
                    keep = abs(cur_val - prev_val) <= 1e-4
                else:
                    keep = (cur_val == prev_val)

            if keep:
                new_matches.append((addr, cur_val))

        elapsed = time.time() - t0
        self.history.append((list(self.candidates), desc))
        self.candidates = new_matches

        print(f"{COLOR_GREEN}[+] Next Scan complete in {elapsed:.3f}s. Remaining: {COLOR_BOLD}{len(new_matches):,}{COLOR_RESET}{COLOR_GREEN} matches.{COLOR_RESET}")
        self.print_candidates(limit=25)
        return len(new_matches)

    def undo(self):
        """ย้อนกลับการ Scan ก่อนหน้า"""
        if not self.history:
            print(f"{COLOR_YELLOW}[!] No scan history to undo.{COLOR_RESET}")
            return
        prev_candidates, desc = self.history.pop()
        self.candidates = prev_candidates
        print(f"{COLOR_GREEN}[+] Reverted '{desc}'. Restored {len(self.candidates):,} candidates.{COLOR_RESET}")
        self.print_candidates(limit=20)

    def format_address(self, addr: int) -> str:
        """จัดรูปแบบ Address พร้อมคำนวณ Offset สัมพันธ์กับ my_unit หรือ binary"""
        tags = []
        if self.my_unit > 0:
            if self.my_unit <= addr < self.my_unit + 0x40000:
                off = addr - self.my_unit
                tags.append(f"{COLOR_GREEN}my_unit + 0x{off:x}{COLOR_RESET}")
            elif self.my_unit - 0x10000 <= addr < self.my_unit:
                off = self.my_unit - addr
                tags.append(f"{COLOR_YELLOW}my_unit - 0x{off:x}{COLOR_RESET}")

        if self.binary_base > 0 and self.binary_base <= addr < self.binary_base + 0x20000000:
            off = addr - self.binary_base
            tags.append(f"{COLOR_CYAN}{self.binary_name} + 0x{off:x}{COLOR_RESET}")

        if getattr(self, 'airstate_base', 0) > 0 and self.airstate_base <= addr < self.airstate_base + 0x3000:
            off = addr - self.airstate_base
            known = ""
            if off == 0x806: known = " [Gun Ammo]"
            elif off == 0x1dfe: known = " [Flare]"
            elif off == 0x1fc6: known = " [Chaff]"
            tags.append(f"{COLOR_MAGENTA}AirState + 0x{off:x}{known}{COLOR_RESET}")

        tag_str = f" ({', '.join(tags)})" if tags else ""
        return f"0x{addr:08x}{tag_str}"

    def print_candidates(self, limit: int = 25):
        """พิมพ์ตาราง Candidate แสดงผลลัพธ์"""
        total = len(self.candidates)
        if total == 0:
            print(f"  {COLOR_GRAY}(No candidates found){COLOR_RESET}")
            return

        print(f"\n{COLOR_BOLD}{'IDX':>4} | {'ADDRESS':<42} | {'VALUE (DEC)':<14} | {'HEX':<10}{COLOR_RESET}")
        print("-" * 75)

        show_count = min(total, limit)
        for i in range(show_count):
            addr, val = self.candidates[i]
            # อ่านค่าล่าสุดสดๆ ณ ขณะนี้
            live_val = self.read_single_value(addr)
            val_to_show = live_val if live_val is not None else val

            formatted_addr = self.format_address(addr)

            if isinstance(val_to_show, float):
                val_str = f"{val_to_show:.4f}"
                hex_str = "float"
            elif isinstance(val_to_show, int):
                val_str = f"{val_to_show:,}"
                hex_str = f"0x{val_to_show & 0xFFFFFFFF:x}" if val_to_show >= 0 else f"-0x{abs(val_to_show):x}"
            else:
                val_str = str(val_to_show)
                hex_str = "-"

            print(f"{i+1:>4} | {formatted_addr:<50} | {val_str:<14} | {hex_str:<10}")

        if total > show_count:
            print(f"{COLOR_GRAY}... and {total - show_count:,} more candidates (use 'list <count>' to show more){COLOR_RESET}")
        print()

    def live_watch(self, limit: int = 25, delay: float = 0.25):
        """โหมด Live Watch มอนิเตอร์ค่า Real-time ในเทอร์มินัลแบบไฮไลต์สี"""
        if not self.candidates:
            print(f"{COLOR_YELLOW}[!] No candidates to watch.{COLOR_RESET}")
            return

        watch_list = self.candidates[:limit]
        last_values = {addr: self.read_single_value(addr) for addr, _ in watch_list}

        print(f"{COLOR_CYAN}[*] Starting Live Watch for top {len(watch_list)} candidates (refresh every {delay}s).")
        print(f"    Press {COLOR_BOLD}Enter{COLOR_RESET}{COLOR_CYAN} or {COLOR_BOLD}Ctrl+C{COLOR_RESET}{COLOR_CYAN} to stop.{COLOR_RESET}\n")

        running = True
        def sig_handler(sig, frame):
            nonlocal running
            running = False
        old_handler = signal.signal(signal.SIGINT, sig_handler)

        try:
            while running:
                # ตรวจสอบการกดปุ่ม Enter โดยไม่บล็อค
                try:
                    if select.select([sys.stdin], [], [], 0)[0]:
                        sys.stdin.readline()
                        break
                except Exception:
                    pass

                output_lines = []
                output_lines.append(f"{COLOR_BOLD}{'IDX':>4} | {'ADDRESS':<42} | {'VALUE':<14} | {'DELTA':<10}{COLOR_RESET}")
                output_lines.append("-" * 75)

                for idx, (addr, _) in enumerate(watch_list):
                    cur_val = self.read_single_value(addr)
                    old_val = last_values.get(addr)
                    last_values[addr] = cur_val

                    formatted_addr = self.format_address(addr)

                    delta_str = ""
                    val_color = COLOR_RESET
                    if cur_val is not None and old_val is not None:
                        if cur_val > old_val:
                            val_color = COLOR_GREEN
                            delta_str = f"{COLOR_GREEN}+{cur_val - old_val}{COLOR_RESET}"
                        elif cur_val < old_val:
                            val_color = COLOR_RED
                            delta_str = f"{COLOR_RED}{cur_val - old_val}{COLOR_RESET}"
                        else:
                            delta_str = f"{COLOR_GRAY}={COLOR_RESET}"

                    val_str = f"{val_color}{str(cur_val):<14}{COLOR_RESET}" if cur_val is not None else "???"
                    output_lines.append(f"{idx+1:>4} | {formatted_addr:<50} | {val_str} | {delta_str}")

                # พิมพ์ทับหน้าจอ
                print("\033[H\033[J" + "\n".join(output_lines), end="", flush=True)
                time.sleep(delay)
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGINT, old_handler)
            print(f"\n{COLOR_YELLOW}[*] Live watch stopped.{COLOR_RESET}\n")

    def write_value(self, addr: int, val: Any) -> bool:
        """เขียนค่าลงหน่วยความจำ"""
        cfg = TYPE_CONFIG[self.data_type]
        fmt = cfg["format"]
        try:
            raw = struct.pack(fmt, val)
            os.pwrite(self.mem_fd, raw, addr)
            print(f"{COLOR_GREEN}[+] Successfully wrote {val} to 0x{addr:08x}{COLOR_RESET}")
            return True
        except Exception as e:
            print(f"{COLOR_RED}[-] Failed to write: {e}{COLOR_RESET}")
            return False

    def save_candidates(self, filename: str):
        """ส่งออกผลลัพธ์ลงไฟล์ข้อความ"""
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"# Global Memory Scanner Results - PID {self.pid} ({self.process_name})\n")
                f.write(f"# Data Type: {self.data_type} | Scope: {self.scope}\n")
                f.write(f"# Total Candidates: {len(self.candidates)}\n\n")
                for idx, (addr, val) in enumerate(self.candidates):
                    live_v = self.read_single_value(addr)
                    f.write(f"[{idx+1}] 0x{addr:08x} = {live_v} (init: {val})\n")
            print(f"{COLOR_GREEN}[+] Saved {len(self.candidates)} candidates to '{filename}'{COLOR_RESET}")
        except Exception as e:
            print(f"{COLOR_RED}[-] Error saving candidates: {e}{COLOR_RESET}")

    def find_pointers(self, target_addr: int, max_results: int = 30):
        """ค้นหา Pointer ในหน่วยความจำที่ชี้มายัง target_addr หรือบริเวณใกล้เคียง (struct offset)"""
        print(f"{COLOR_CYAN}[*] Scanning memory for pointers pointing to 0x{target_addr:08x} (struct window: +/- 0x8000)...{COLOR_RESET}")
        scoped_regions = self.get_scoped_regions()
        matches = []

        t0 = time.time()
        for reg in scoped_regions:
            cur = reg.start
            while cur < reg.end:
                sz = min(self.chunk_size, reg.end - cur)
                usable = sz - (sz % 8)
                if usable < 8:
                    break
                try:
                    data = os.pread(self.mem_fd, usable, cur)
                    if len(data) >= 8:
                        arr = np.frombuffer(data[:len(data) - (len(data) % 8)], dtype=np.uint64)
                        # หาค่าที่ชี้ตรงๆ หรือชี้ที่หัว struct
                        exact = np.nonzero(arr == target_addr)[0]
                        for idx in exact:
                            matches.append((cur + int(idx) * 8, 0))

                        # หาค่าที่ชี้ในช่วง offset [0, 0x8000]
                        near = np.nonzero((arr >= target_addr - 0x8000) & (arr < target_addr))[0]
                        for idx in near:
                            base_ptr = int(arr[idx])
                            matches.append((cur + int(idx) * 8, target_addr - base_ptr))
                except Exception:
                    pass
                cur += usable
                if len(matches) >= max_results * 3:
                    break

        elapsed = time.time() - t0
        print(f"{COLOR_GREEN}[+] Pointer scan finished in {elapsed:.3f}s. Found {len(matches)} pointers:{COLOR_RESET}")
        for p_addr, off in matches[:max_results]:
            fmt_p = self.format_address(p_addr)
            if off == 0:
                print(f"  Pointer at {fmt_p} -> 0x{target_addr:08x} (Direct Pointer)")
            else:
                print(f"  Pointer at {fmt_p} -> Base + 0x{off:x} (points to base of struct)")

    def hex_dump(self, addr: int, size: int = 64):
        """แสดงผล Hex Dump สไตล์ x64dbg / Cheat Engine"""
        try:
            data = os.pread(self.mem_fd, size, addr)
        except Exception as e:
            print(f"{COLOR_RED}[-] Failed to read memory at 0x{addr:08x}: {e}{COLOR_RESET}")
            return

        print(f"\n{COLOR_BOLD}Hex Dump at {self.format_address(addr)} ({size} bytes):{COLOR_RESET}")
        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            hex_bytes = " ".join(f"{b:02x}" for b in chunk)
            ascii_chars = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
            print(f"  0x{addr + i:08x}:  {hex_bytes:<48}  |{ascii_chars}|")
        print()


def parse_number(val_str: str, data_type: str) -> Any:
    """แปลงสตริงตัวเลขเป็นชนิดข้อมูลที่ถูกต้อง (รองรับ hex 0x... และ float)"""
    val_str = val_str.strip()
    if data_type in ("f32", "f64"):
        return float(val_str)
    if val_str.lower().startswith("0x"):
        return int(val_str, 16)
    return int(val_str)


def run_interactive_shell(scanner: GlobalMemoryScanner):
    """รัน REPL Interactive Shell สไตล์ Cheat Engine"""
    print(f"""
{COLOR_CYAN}{COLOR_BOLD}======================================================================
  CHEAT ENGINE STYLE GLOBAL MEMORY SCANNER (Linux / War Thunder)
======================================================================{COLOR_RESET}
  Target: {COLOR_GREEN}{scanner.process_name} (PID: {scanner.pid}){COLOR_RESET}
  Scope : {COLOR_YELLOW}{scanner.scope}{COLOR_RESET}  |  Type: {COLOR_YELLOW}{scanner.data_type} ({TYPE_CONFIG[scanner.data_type]['name']}){COLOR_RESET}
  Player Unit: {COLOR_GREEN}{f'0x{scanner.my_unit:08x}' if scanner.my_unit else 'Not detected'}{COLOR_RESET}
----------------------------------------------------------------------
  {COLOR_BOLD}COMMANDS:{COLOR_RESET}
    {COLOR_BOLD}scan <val>{COLOR_RESET} (or {COLOR_BOLD}s{COLOR_RESET})      : First Scan for value (e.g. 's 17')
    {COLOR_BOLD}next <val>{COLOR_RESET} (or {COLOR_BOLD}n{COLOR_RESET})      : Next Scan for exact value (e.g. 'n 16')
    {COLOR_BOLD}dec [amt]{COLOR_RESET} (or {COLOR_BOLD}-{COLOR_RESET})       : Filter decreased (or decreased by amt, e.g. 'dec 1')
    {COLOR_BOLD}inc [amt]{COLOR_RESET} (or {COLOR_BOLD}+{COLOR_RESET})       : Filter increased (or increased by amt, e.g. 'inc 1')
    {COLOR_BOLD}chg{COLOR_RESET}                   : Filter changed value
    {COLOR_BOLD}same{COLOR_RESET}                  : Filter unchanged value
    {COLOR_BOLD}undo{COLOR_RESET}                  : Undo last scan
    {COLOR_BOLD}watch{COLOR_RESET} (or {COLOR_BOLD}w{COLOR_RESET})         : Live real-time candidate monitor table
    {COLOR_BOLD}list [count]{COLOR_RESET} (or {COLOR_BOLD}l{COLOR_RESET})  : List candidates (default 25)
    {COLOR_BOLD}type <i32|u32|f32|i16|i64> : Change data type
    {COLOR_BOLD}scope <heap|anon|unit|rw|all> : Change search scope (heap=fastest, unit=player)
    {COLOR_BOLD}dump <addr> [size]{COLOR_RESET} : Hex dump memory at address
    {COLOR_BOLD}ptr <addr>{COLOR_RESET}          : Scan for pointers pointing to address
    {COLOR_BOLD}clear{COLOR_RESET} (or {COLOR_BOLD}reset{COLOR_RESET})    : Clear candidates for fresh scan
    {COLOR_BOLD}help{COLOR_RESET} (or {COLOR_BOLD}?{COLOR_RESET})          : Show this help
    {COLOR_BOLD}exit{COLOR_RESET} (or {COLOR_BOLD}q{COLOR_RESET})          : Quit scanner
======================================================================
""")

    while True:
        try:
            cand_count = len(scanner.candidates)
            cand_badge = f"{COLOR_GREEN}{cand_count:,} matches{COLOR_RESET}" if cand_count > 0 else f"{COLOR_GRAY}0 matches{COLOR_RESET}"
            prompt = f"[{COLOR_CYAN}{scanner.process_name}{COLOR_RESET}|{COLOR_YELLOW}{scanner.data_type}{COLOR_RESET}|{COLOR_MAGENTA}{scanner.scope}{COLOR_RESET}|{cand_badge}]> "

            user_input = input(prompt).strip()
            if not user_input:
                continue

            parts = user_input.split()
            cmd = parts[0].lower()
            args = parts[1:]

            if cmd in ("exit", "quit", "q"):
                print("Exiting memory scanner. Goodbye!")
                break

            elif cmd in ("help", "?"):
                print("""
Commands:
  scan <value> / s <value>    : First Scan for value
  next <value> / n <value>    : Next Scan for exact value
  dec [amt] / - [amt]         : Filter decreased value (or decreased by amt)
  inc [amt] / + [amt]         : Filter increased value (or increased by amt)
  chg                         : Filter changed value
  same / unchg                : Filter unchanged value
  undo                        : Undo last scan step
  watch / w [limit]           : Real-time live monitor of candidate values
  list [count] / l            : Print candidate table
  scope <heap|anon|unit|rw>   : Change scan scope
  type <i32|u32|f32|i16|i64>  : Change data type
  dump <addr> [size]          : Hex dump address
  ptr <addr>                  : Scan for pointers to address
  clear / reset               : Reset all candidates
                """)

            elif cmd in ("scan", "s", "first"):
                if not args:
                    print(f"{COLOR_YELLOW}[!] Usage: scan <value> [max_val]  (e.g. scan 17, or scan 10 20){COLOR_RESET}")
                    continue
                try:
                    if ".." in args[0]:
                        p_rng = args[0].split("..")
                        min_v = parse_number(p_rng[0], scanner.data_type)
                        max_v = parse_number(p_rng[1], scanner.data_type)
                        scanner.first_scan(min_v, val_max=max_v)
                    elif len(args) >= 2:
                        min_v = parse_number(args[0], scanner.data_type)
                        max_v = parse_number(args[1], scanner.data_type)
                        scanner.first_scan(min_v, val_max=max_v)
                    else:
                        val = parse_number(args[0], scanner.data_type)
                        scanner.first_scan(val)
                except ValueError:
                    print(f"{COLOR_RED}[-] Invalid number format: '{args[0]}'{COLOR_RESET}")

            elif cmd in ("next", "n", "filter", "f"):
                if not args:
                    print(f"{COLOR_YELLOW}[!] Usage: next <value> [max_val]  (e.g. next 16){COLOR_RESET}")
                    continue
                try:
                    if ".." in args[0]:
                        p_rng = args[0].split("..")
                        min_v = parse_number(p_rng[0], scanner.data_type)
                        max_v = parse_number(p_rng[1], scanner.data_type)
                        scanner.next_scan(op="between", target_val=min_v, val_max=max_v)
                    elif len(args) >= 2:
                        min_v = parse_number(args[0], scanner.data_type)
                        max_v = parse_number(args[1], scanner.data_type)
                        scanner.next_scan(op="between", target_val=min_v, val_max=max_v)
                    else:
                        val = parse_number(args[0], scanner.data_type)
                        scanner.next_scan(op="exact", target_val=val)
                except ValueError:
                    print(f"{COLOR_RED}[-] Invalid number format: '{args[0]}'{COLOR_RESET}")

            elif cmd in ("between", "range"):
                if len(args) < 2:
                    print(f"{COLOR_YELLOW}[!] Usage: between <min> <max>  (e.g. between 10 20){COLOR_RESET}")
                    continue
                try:
                    min_v = parse_number(args[0], scanner.data_type)
                    max_v = parse_number(args[1], scanner.data_type)
                    if not scanner.candidates:
                        scanner.first_scan(min_v, val_max=max_v)
                    else:
                        scanner.next_scan(op="between", target_val=min_v, val_max=max_v)
                except ValueError:
                    print(f"{COLOR_RED}[-] Invalid number format.{COLOR_RESET}")

            elif cmd in ("write", "wmem", "set"):
                if len(args) < 2:
                    print(f"{COLOR_YELLOW}[!] Usage: write <hex_address> <value>{COLOR_RESET}")
                    continue
                try:
                    addr = int(args[0], 16) if args[0].startswith("0x") else int(args[0])
                    val = parse_number(args[1], scanner.data_type)
                    scanner.write_value(addr, val)
                except Exception as e:
                    print(f"{COLOR_RED}[-] Write error: {e}{COLOR_RESET}")

            elif cmd in ("save", "export"):
                fname = args[0] if args else "scan_results.txt"
                scanner.save_candidates(fname)

            elif cmd in ("dec", "decreased", "-"):
                delta = None
                if args:
                    try:
                        delta = parse_number(args[0], scanner.data_type)
                    except ValueError:
                        print(f"{COLOR_RED}[-] Invalid delta: '{args[0]}'{COLOR_RESET}")
                        continue
                scanner.next_scan(op="decreased", delta=delta)

            elif cmd in ("inc", "increased", "+"):
                delta = None
                if args:
                    try:
                        delta = parse_number(args[0], scanner.data_type)
                    except ValueError:
                        print(f"{COLOR_RED}[-] Invalid delta: '{args[0]}'{COLOR_RESET}")
                        continue
                scanner.next_scan(op="increased", delta=delta)

            elif cmd in ("chg", "changed"):
                scanner.next_scan(op="changed")

            elif cmd in ("same", "unchanged", "unchg"):
                scanner.next_scan(op="unchanged")

            elif cmd in ("undo", "back"):
                scanner.undo()

            elif cmd in ("watch", "w", "monitor"):
                limit = int(args[0]) if args and args[0].isdigit() else 25
                scanner.live_watch(limit=limit)

            elif cmd in ("list", "l", "show"):
                count = int(args[0]) if args and args[0].isdigit() else 25
                scanner.print_candidates(limit=count)

            elif cmd in ("clear", "reset"):
                scanner.candidates.clear()
                scanner.history.clear()
                print(f"{COLOR_GREEN}[+] Candidates cleared. Ready for fresh scan.{COLOR_RESET}")

            elif cmd in ("type", "t"):
                if not args or args[0] not in TYPE_CONFIG:
                    types_list = ", ".join(TYPE_CONFIG.keys())
                    print(f"{COLOR_YELLOW}[!] Available types: {types_list}{COLOR_RESET}")
                else:
                    scanner.data_type = args[0]
                    scanner.alignment = TYPE_CONFIG[scanner.data_type]["size"]
                    print(f"{COLOR_GREEN}[+] Data type changed to {scanner.data_type} ({TYPE_CONFIG[scanner.data_type]['name']}){COLOR_RESET}")

            elif cmd in ("scope",):
                valid_scopes = ("heap", "anon", "unit", "air", "airstate", "rw", "module", "all")
                if not args or args[0] not in valid_scopes:
                    print(f"{COLOR_YELLOW}[!] Available scopes: {', '.join(valid_scopes)}{COLOR_RESET}")
                    print(f"    - heap   : Only [heap] region (Fastest, where player unit & entities live)")
                    print(f"    - unit   : Only around player my_unit (Instant!)")
                    print(f"    - air    : Only AirState / HUD table (Live Ammo, Flare, Chaff - 0.001s!)")
                    print(f"    - anon   : Anonymous memory + heap (Excludes large file maps)")
                    print(f"    - rw     : All writable memory regions")
                    print(f"    - module : Main executable bss/data")
                    print(f"    - all    : All readable memory")
                else:
                    scanner.scope = args[0]
                    print(f"{COLOR_GREEN}[+] Scope changed to '{scanner.scope}'{COLOR_RESET}")

            elif cmd in ("dump", "hex", "d"):
                if not args:
                    print(f"{COLOR_YELLOW}[!] Usage: dump <hex_address> [size]{COLOR_RESET}")
                    continue
                try:
                    addr = int(args[0], 16) if args[0].startswith("0x") else int(args[0])
                    size = int(args[1]) if len(args) > 1 else 64
                    scanner.hex_dump(addr, size)
                except Exception as e:
                    print(f"{COLOR_RED}[-] Error: {e}{COLOR_RESET}")

            elif cmd in ("ptr", "findptr"):
                if not args:
                    print(f"{COLOR_YELLOW}[!] Usage: ptr <hex_address>{COLOR_RESET}")
                    continue
                try:
                    addr = int(args[0], 16) if args[0].startswith("0x") else int(args[0])
                    scanner.find_pointers(addr)
                except Exception as e:
                    print(f"{COLOR_RED}[-] Error: {e}{COLOR_RESET}")

            elif cmd in ("myunit", "unit"):
                scanner.detect_game_pointers()
                if scanner.my_unit:
                    print(f"{COLOR_GREEN}[+] my_unit = 0x{scanner.my_unit:08x}{COLOR_RESET}")
                else:
                    print(f"{COLOR_YELLOW}[!] my_unit not detected.{COLOR_RESET}")

            else:
                # ตรวจสอบว่าเป็นตัวเลขโดดๆ หรือไม่ -> ถ้าใช่ให้ถือว่าเป็น next scan หรือ first scan
                try:
                    val = parse_number(cmd, scanner.data_type)
                    if not scanner.candidates:
                        scanner.first_scan(val)
                    else:
                        scanner.next_scan(op="exact", target_val=val)
                except ValueError:
                    print(f"{COLOR_YELLOW}[!] Unknown command: '{cmd}'. Type 'help' for available commands.{COLOR_RESET}")

        except (EOFError, KeyboardInterrupt):
            print("\nExiting memory scanner. Goodbye!")
            break
        except Exception as e:
            print(f"{COLOR_RED}[-] Exception: {e}{COLOR_RESET}")


def find_target_pid(process_name: str = "aces") -> Optional[int]:
    """ค้นหา PID ของโปรเซสอัตโนมัติ"""
    try:
        import subprocess
        output = subprocess.check_output(["pgrep", "-a", process_name]).decode("utf-8")
        for line in output.strip().split("\n"):
            parts = line.split(maxsplit=1)
            if parts and parts[0].isdigit():
                # ตรวจสอบว่าไม่ใช่ตัวสคริปต์นี้เอง
                if "global_memory_scanner" in line:
                    continue
                return int(parts[0])
    except Exception:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Cheat Engine style Global Memory Scanner for Linux / War Thunder")
    parser.add_argument("--pid", type=int, help="Target process PID")
    parser.add_argument("--process", type=str, default="aces", help="Target process name (default: aces)")
    parser.add_argument("--type", type=str, default="i32", choices=list(TYPE_CONFIG.keys()), help="Data type (default: i32)")
    parser.add_argument("--scope", type=str, default="heap", choices=["heap", "anon", "unit", "rw", "module", "all"], help="Scan scope (default: heap)")
    parser.add_argument("--scan", type=str, help="Initial scan value (e.g. --scan 17)")

    args = parser.parse_args()

    pid = args.pid
    if not pid:
        pid = find_target_pid(args.process)
        if not pid:
            print(f"{COLOR_RED}[-] Process '{args.process}' not found! Specify --pid <PID>{COLOR_RESET}")
            sys.exit(1)
        print(f"{COLOR_GREEN}[+] Auto-detected process '{args.process}' -> PID {pid}{COLOR_RESET}")

    scanner = GlobalMemoryScanner(pid=pid, data_type=args.type, scope=args.scope)
    if not scanner.open_process():
        sys.exit(1)

    try:
        if args.scan is not None:
            val = parse_number(args.scan, args.type)
            scanner.first_scan(val)

        run_interactive_shell(scanner)
    finally:
        scanner.close()


if __name__ == "__main__":
    main()
