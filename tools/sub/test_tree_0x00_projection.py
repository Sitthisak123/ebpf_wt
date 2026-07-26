import sys, os, struct, math
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import is_valid_ptr, world_to_screen, get_view_matrix
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    
    box_data = mul.get_unit_3d_box_data(scanner, my_unit)
    unit_pos, unit_rot = box_data[0], box_data[3]
    view_matrix = get_view_matrix(scanner, base_addr)
    
    raw_ptr = scanner.read_mem(my_unit + 0x238, 8)
    tree_ptr = struct.unpack("<Q", raw_ptr)[0]
    wtm_raw = scanner.read_mem(tree_ptr + 0x00, 8)
    w_ptr = struct.unpack("<Q", wtm_raw)[0]
    
    idx = 348 # bone_gun
    matrix_data = scanner.read_mem(w_ptr + idx * 64, 64)
    r0 = struct.unpack_from("<fff", matrix_data, 0x00) # X axis
    r1 = struct.unpack_from("<fff", matrix_data, 0x10) # Y axis
    r2 = struct.unpack_from("<fff", matrix_data, 0x20) # Z axis
    r3 = struct.unpack_from("<fff", matrix_data, 0x30) # Local Pos
    
    def to_world(lx, ly, lz):
        return (lx*unit_rot[0] + ly*unit_rot[3] + lz*unit_rot[6] + unit_pos[0],
                lx*unit_rot[1] + ly*unit_rot[4] + lz*unit_rot[7] + unit_pos[1],
                lx*unit_rot[2] + ly*unit_rot[5] + lz*unit_rot[8] + unit_pos[2])

    length = 8.0
    bx, by, bz = r3[0], r3[1], r3[2]
    
    # Try both R0, R1, R2 as forward vector
    for axis_name, axis_vec in [("R0 (X)", r0), ("R1 (Y)", r1), ("R2 (Z)", r2)]:
        fx_x, fx_y, fx_z = axis_vec[0], axis_vec[1], axis_vec[2]
        base_world = to_world(bx, by, bz)
        tip_world = to_world(bx + fx_x * length, by + fx_y * length, bz + fx_z * length)
        
        scr_b = world_to_screen(view_matrix, base_world[0], base_world[1], base_world[2], 1920, 1080) if view_matrix else None
        scr_t = world_to_screen(view_matrix, tip_world[0], tip_world[1], tip_world[2], 1920, 1080) if view_matrix else None
        
        print(f"\nAxis {axis_name}: {axis_vec}")
        print(f"  Base World: {base_world}")
        print(f"  Tip World:  {tip_world}")
        print(f"  Screen Base: {scr_b}")
        print(f"  Screen Tip:  {scr_t}")

if __name__ == '__main__':
    main()
