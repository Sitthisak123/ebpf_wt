import sys, os, struct, math, time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import is_valid_ptr, world_to_screen, get_view_matrix, get_unit_3d_box_data, get_local_team

def main():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)
    
    my_unit, _ = get_local_team(scanner, base_addr)
    box_data = get_unit_3d_box_data(scanner, my_unit)
    unit_pos, unit_rot = box_data[0], box_data[3]
    
    raw_ptr = scanner.read_mem(my_unit + 0x238, 8)
    tree_ptr = struct.unpack("<Q", raw_ptr)[0]
    wtm_raw = scanner.read_mem(tree_ptr + 0x00, 8)
    w_ptr = struct.unpack("<Q", wtm_raw)[0]
    
    idx = 348 # bone_gun
    print("Monitoring Row 0 (0x00) for barrel pitch and yaw... (5 seconds)")
    for s in range(10):
        time.sleep(0.5)
        mat = scanner.read_mem(w_ptr + idx * 64, 64)
        r0 = struct.unpack_from("<fff", mat, 0x00)
        pitch_deg = math.degrees(math.asin(max(-1.0, min(1.0, r0[1]))))
        print(f"[{s*0.5:.1f}s] Row0: ({r0[0]:.4f}, {r0[1]:.4f}, {r0[2]:.4f}) -> Pitch Angle: {pitch_deg:+.2f}°")

if __name__ == '__main__':
    main()
