import sys, os, struct, math
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import is_valid_ptr, world_to_screen
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    
    # Get my_unit info
    box_data = mul.get_unit_3d_box_data(scanner, my_unit)
    pos, R = box_data[0], box_data[3]
    view_matrix = mul.get_view_matrix(scanner, base_addr)
    
    raw_ptr = scanner.read_mem(my_unit + 0x238, 8)
    tree_ptr = struct.unpack("<Q", raw_ptr)[0]
    
    # Read tree + 0x00 (Dynamic WTM array)
    wtm_raw = scanner.read_mem(tree_ptr + 0x00, 8)
    w_ptr = struct.unpack("<Q", wtm_raw)[0]
    
    idx = 348 # bone_gun
    matrix_data = scanner.read_mem(w_ptr + idx * 64, 64)
    r0 = struct.unpack_from("<fff", matrix_data, 0x00)
    r1 = struct.unpack_from("<fff", matrix_data, 0x10)
    r2 = struct.unpack_from("<fff", matrix_data, 0x20)
    r3 = struct.unpack_from("<fff", matrix_data, 0x30)
    
    print(f"My Unit Pos: {pos}")
    print(f"Bone {idx} (tree+0x00):")
    print(f"  Row0 (X-axis): ({r0[0]:.4f}, {r0[1]:.4f}, {r0[2]:.4f})")
    print(f"  Row1 (Y-axis): ({r1[0]:.4f}, {r1[1]:.4f}, {r1[2]:.4f})")
    print(f"  Row2 (Z-axis): ({r2[0]:.4f}, {r2[1]:.4f}, {r2[2]:.4f})")
    print(f"  Row3 (Pos):    ({r3[0]:.4f}, {r3[1]:.4f}, {r3[2]:.4f})")

if __name__ == '__main__':
    main()
