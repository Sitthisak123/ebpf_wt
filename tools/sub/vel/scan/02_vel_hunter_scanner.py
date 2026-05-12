import os
import sys
import struct
import time
import math

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_cgame_base, get_all_units, get_local_team, get_unit_pos, get_view_matrix, world_to_screen

SCREEN_WIDTH, SCREEN_HEIGHT = 2560, 1440
CENTER_X, CENTER_Y = SCREEN_WIDTH / 2.0, SCREEN_HEIGHT / 2.0

def get_baseline_velocity(scanner, target_ptr):
    try:
        move_raw = scanner.read_mem(target_ptr + 0x0018, 8)
        if not move_raw: return None
        move_ptr = struct.unpack("<Q", move_raw)[0]
        if move_ptr < 0x10000: return None
        
        vel_raw = scanner.read_mem(move_ptr + 0x0318, 12)
        if not vel_raw: return None
        vx, vy, vz = struct.unpack("<fff", vel_raw)
        
        if any(abs(v) > 0.1 for v in (vx, vy, vz)):
            return (vx, vy, vz), move_ptr
        return None, move_ptr
    except: return None, 0

def smart_memory_sweep(scanner, base_ptr, baseline_vel, size=0x4000, tolerance=5.0):
    """ 
    🚀 THE ±5 LOGIC: เช็คทีละแกนว่าอยู่ในระยะ +5 / -5 จากแม่แบบหรือไม่ 
    """
    candidates = []
    buffer = scanner.read_mem(base_ptr, size)
    if not buffer: return []

    bx, by, bz = baseline_vel

    # สแกนหา FLOAT (12 bytes)
    for offset in range(0, size - 12, 4):
        x, y, z = struct.unpack_from("<fff", buffer, offset)
        if math.isfinite(x) and math.isfinite(y) and math.isfinite(z):
            # อนุญาตให้แต่ละแกนคลาดเคลื่อนได้ ±5 (ตามคอนเซปต์ท่านนายพล)
            if abs(x - bx) <= tolerance and abs(y - by) <= tolerance and abs(z - bz) <= tolerance:
                if any(abs(v) > 0.1 for v in (x,y,z)):
                    candidates.append({"offset": offset, "type": "FLOAT", "last_val": (x,y,z), "ticks": 0})

    # สแกนหา DOUBLE (24 bytes)
    for offset in range(0, size - 24, 8):
        x, y, z = struct.unpack_from("<ddd", buffer, offset)
        if math.isfinite(x) and math.isfinite(y) and math.isfinite(z):
            if abs(x - bx) <= tolerance and abs(y - by) <= tolerance and abs(z - bz) <= tolerance:
                if any(abs(v) > 0.1 for v in (x,y,z)):
                    candidates.append({"offset": offset, "type": "DOUBLE", "last_val": (x,y,z), "ticks": 0})

    return candidates

def monitor_tick_rates(scanner, base_ptr, candidates, monitor_time=1.0):
    start_time = time.time()
    loops = 0
    
    while time.time() - start_time < monitor_time:
        loops += 1
        for cand in candidates:
            try:
                if cand["type"] == "FLOAT":
                    raw = scanner.read_mem(base_ptr + cand["offset"], 12)
                    val = struct.unpack("<fff", raw)
                else:
                    raw = scanner.read_mem(base_ptr + cand["offset"], 24)
                    val = struct.unpack("<ddd", raw)
                
                # เช็คการอัปเดต (ตั้งค่าความเซนซิทีฟไว้ที่ 0.001)
                diff = abs(val[0] - cand["last_val"][0]) + abs(val[1] - cand["last_val"][1]) + abs(val[2] - cand["last_val"][2])
                if diff > 0.001:
                    cand["ticks"] += 1
                    cand["last_val"] = val
            except: pass
            
        time.sleep(1/144.0) 
        
    return loops

def main():
    print("[*] Starting V2 SMART High-Tick Scanner (±5 Tolerance)...")
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_address)

    while True:
        os.system('clear')
        print("=== 🧠 V2 SMART TICK-RATE SCANNER (±5 MODE) ===")
        cgame_base = get_cgame_base(scanner, base_address)
        if not cgame_base: continue

        my_unit_ptr, _ = get_local_team(scanner, cgame_base)
        all_units = get_all_units(scanner, cgame_base)
        view_matrix = get_view_matrix(scanner, cgame_base)

        if not all_units or not view_matrix:
            print("⏳ รอข้อมูล...")
            time.sleep(0.5)
            continue

        enemies = []
        for u_ptr, is_air in all_units:
            if u_ptr == my_unit_ptr: continue
            u_pos = get_unit_pos(scanner, u_ptr)
            if not u_pos: continue
            scr_pos = world_to_screen(view_matrix, u_pos[0], u_pos[1], u_pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
            if scr_pos and scr_pos[2] > 0:
                dist = math.hypot(scr_pos[0] - CENTER_X, scr_pos[1] - CENTER_Y)
                enemies.append((dist, u_ptr))
        
        if not enemies:
            print("👀 ไม่พบศัตรูหน้าจอ...")
            time.sleep(0.1)
            continue

        enemies.sort(key=lambda x: x[0])
        target_ptr = enemies[0][1]

        baseline_vel, move_ptr = get_baseline_velocity(scanner, target_ptr)
        if not baseline_vel:
            print(f"🔴 รอศัตรูเคลื่อนที่ (หาแม่แบบ 5Hz ไม่เจอ)...")
            time.sleep(0.1)
            continue

        print(f"\n✅ 1. เจอแม่แบบ (Baseline): X:{baseline_vel[0]:.1f} Y:{baseline_vel[1]:.1f} Z:{baseline_vel[2]:.1f}")
        print(f"🔍 2. กวาด Memory แบบ ±5 หาตัว Interpolate (รอ 1 วินาที เล็งเป้าค้างไว้!)...")

        cand_unit = smart_memory_sweep(scanner, target_ptr, baseline_vel, size=0x4000, tolerance=5.0)
        cand_move = smart_memory_sweep(scanner, move_ptr, baseline_vel, size=0x4000, tolerance=5.0)

        total_loops = monitor_tick_rates(scanner, target_ptr, cand_unit)
        _ = monitor_tick_rates(scanner, move_ptr, cand_move)

        print(f"🔄 ความเร็ว Loop สแกนเนอร์: {total_loops} ครั้ง/วินาที")
        print("\n🏆 --- ผลลัพธ์: ອอฟเซ็ตที่มีพฤติกรรมคล้ายความเร็ว ---")
        
        cand_unit.sort(key=lambda x: x["ticks"], reverse=True)
        cand_move.sort(key=lambda x: x["ticks"], reverse=True)

        print("\n📁 กลุ่ม UNIT POINTER (Base):")
        if not cand_unit: print("   (ไม่พบ Offset ที่เข้าข่าย ±5)")
        for c in cand_unit[:5]:
            hz = "⚡ High Tick (สมูท)!" if c['ticks'] > 20 else f"Low ({c['ticks']}Hz)"
            print(f"   [Unit + {hex(c['offset'])}] | {c['type']} | Ticks: {c['ticks']} | {hz}")
            print(f"   -> ค่าล่าสุด: X:{c['last_val'][0]:.1f} Y:{c['last_val'][1]:.1f} Z:{c['last_val'][2]:.1f}")

        print("\n📁 กลุ่ม MOVE POINTER (0x018):")
        if not cand_move: print("   (ไม่พบ Offset ที่เข้าข่าย ±5)")
        for c in cand_move[:5]:
            hz = "⚡ High Tick (สมูท)!" if c['ticks'] > 20 else f"Low ({c['ticks']}Hz)"
            if c['offset'] == 0x318: hz += " (ตัว Network 5Hz)"
            print(f"   [Move + {hex(c['offset'])}] | {c['type']} | Ticks: {c['ticks']} | {hz}")
            print(f"   -> ค่าล่าสุด: X:{c['last_val'][0]:.1f} Y:{c['last_val'][1]:.1f} Z:{c['last_val'][2]:.1f}")

        print("\n[Ctrl+C] to Exit")
        time.sleep(1)

if __name__ == '__main__':
    main()