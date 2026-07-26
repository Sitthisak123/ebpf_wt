import sys, os, struct, math
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
    view_matrix = get_view_matrix(scanner, base_addr)
    
    raw_ptr = scanner.read_mem(my_unit + 0x238, 8)
    tree_ptr = struct.unpack("<Q", raw_ptr)[0]
    
    wtm_raw = scanner.read_mem(tree_ptr + 0x00, 8)
    w_ptr = struct.unpack("<Q", wtm_raw)[0]
    
    idx = 348 # bone_gun
    mat = scanner.read_mem(w_ptr + idx * 64, 64)
    
    r0 = struct.unpack_from("<fff", mat, 0x00) # Row 0
    r1 = struct.unpack_from("<fff", mat, 0x10) # Row 1
    r2 = struct.unpack_from("<fff", mat, 0x20) # Row 2
    r3 = struct.unpack_from("<fff", mat, 0x30) # Local Pos
    
    def to_world(lx, ly, lz):
        return (lx*unit_rot[0] + ly*unit_rot[3] + lz*unit_rot[6] + unit_pos[0],
                lx*unit_rot[1] + ly*unit_rot[4] + lz*unit_rot[7] + unit_pos[1],
                lx*unit_rot[2] + ly*unit_rot[5] + lz*unit_rot[8] + unit_pos[2])

    base_world = to_world(r3[0], r3[1], r3[2])
    
    print("=== TESTING ALL 3 ROW AXES FOR BARREL FORWARD DIRECTION ===")
    print(f"Base World Pos: ({base_world[0]:.2f}, {base_world[1]:.2f}, {base_world[2]:.2f})")
    
    for row_name, row_vec in [("Row 0 (offset 0x00)", r0), ("Row 1 (offset 0x10)", r1), ("Row 2 (offset 0x20)", r2)]:
        fx, fy, fz = row_vec
        tip_world = to_world(r3[0] + fx*8.0, r3[1] + fy*8.0, r3[2] + fz*8.0)
        
        scr_b = world_to_screen(view_matrix, base_world[0], base_world[1], base_world[2], 1920, 1080) if view_matrix else None
        scr_t = world_to_screen(view_matrix, tip_world[0], tip_world[1], tip_world[2], 1920, 1080) if view_matrix else None
        
        print(f"\n{row_name}: vector=({fx:.4f}, {fy:.4f}, {fz:.4f})")
        print(f"  Tip World Pos: ({tip_world[0]:.2f}, {tip_world[1]:.2f}, {tip_world[2]:.2f})")
        print(f"  Screen Base  : {scr_b}")
        print(f"  Screen Tip   : {scr_t}")

if __name__ == '__main__':
    main()
