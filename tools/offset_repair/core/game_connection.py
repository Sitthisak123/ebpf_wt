import os
import sys
import struct
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address
import src.utils.mul as mul


class GameContext:
    def __init__(self):
        self.pid = None
        self.base_address = 0
        self.scanner = None
        self.cgame_ptr = 0
        self.my_unit_ptr = 0
        self.current_unit_name = "Unknown"
        self.current_unit_type = "Unknown"
        self.is_connected = False
        self.last_check_time = 0
        self.cached_status = "Disconnected"

    def refresh(self, force=False):
        now = time.time()
        if not force and now - self.last_check_time < 0.5:
            return self.is_connected

        self.last_check_time = now
        pid = get_game_pid()
        if not pid:
            self.pid = None
            self.scanner = None
            self.is_connected = False
            self.cached_status = "Game 'aces' not found (Process offline)"
            return False

        if self.pid != pid or self.scanner is None:
            self.pid = pid
            self.base_address = get_game_base_address(pid)
            try:
                self.scanner = MemoryScanner(pid)
            except PermissionError:
                self.scanner = None
                self.is_connected = False
                self.cached_status = f"ตรวจพบเกม PID {pid} แต่สิทธิ์ไม่พอ (กรุณารันด้วย sudo หรือตั้งค่า ptrace)"
                return False
            except Exception as e:
                self.scanner = None
                self.is_connected = False
                self.cached_status = f"ไม่สามารถเชื่อมต่อ PID {pid}: {e}"
                return False

        # Read CGame and MyUnit if possible
        if self.base_address:
            try:
                # Read CGame pointer
                cgame_raw = self.scanner.read_mem(self.base_address + mul.MANAGER_OFFSET, 8)
                if cgame_raw and len(cgame_raw) == 8:
                    cand_cgame = struct.unpack("<Q", cgame_raw)[0]
                    if mul.is_valid_ptr(cand_cgame):
                        self.cgame_ptr = cand_cgame
                    else:
                        self.cgame_ptr = 0
                else:
                    self.cgame_ptr = 0

                # Read MyUnit pointer
                my_unit_ptr = 0
                if self.base_address:
                    my_unit_ptr = mul.get_my_unit(self.scanner, self.base_address)

                # 🧬 DNA Scan Fallback: หากยังไม่พบ ให้ใช้ PAT_MY_UNIT สแกนหาตำแหน่งใหม่ทันที
                if not my_unit_ptr and self.scanner:
                    try:
                        from src.utils.scanner import PAT_MY_UNIT
                        found_hero = self.scanner.find_all_patterns(PAT_MY_UNIT)
                        if found_hero:
                            target_addr = found_hero[0]
                            raw_h = self.scanner.read_mem(target_addr, 8)
                            if raw_h and len(raw_h) == 8:
                                cand_ptr = struct.unpack("<Q", raw_h)[0]
                                if mul.is_valid_ptr(cand_ptr):
                                    my_unit_ptr = cand_ptr
                                    mul.DAT_CONTROLLED_UNIT = target_addr
                    except Exception:
                        pass

                self.my_unit_ptr = my_unit_ptr

                if self.my_unit_ptr:
                    dna = mul.get_unit_detailed_dna(self.scanner, self.my_unit_ptr) or {}
                    self.current_unit_name = dna.get("short_name") or dna.get("name_key") or "ActiveUnit"
                    # Check air or ground
                    raw_type = self.scanner.read_mem(self.my_unit_ptr + mul.OFF_UNIT_TYPE, 1)
                    if raw_type and len(raw_type) == 1:
                        t_val = raw_type[0]
                        self.current_unit_type = "air" if t_val in (1, 2) else "ground"
                    else:
                        self.current_unit_type = "ground"
                    self.cached_status = f"Connected (PID {self.pid}) | Unit: {self.current_unit_name} [{self.current_unit_type.upper()}]"
                else:
                    self.current_unit_name = "None (In Hangar / Not Spawned)"
                    self.current_unit_type = "None"
                    self.cached_status = f"Connected (PID {self.pid}) | Waiting for Unit Spawn (Test Drive)"

                self.is_connected = True
                return True
            except Exception as e:
                self.is_connected = False
                self.cached_status = f"Connection error: {e}"
                return False
        else:
            self.is_connected = False
            self.cached_status = f"PID {self.pid} found but base address 0"
            return False
