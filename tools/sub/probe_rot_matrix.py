import sys, os, struct, math
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_weapon_barrel, is_valid_ptr, get_unit_3d_box_data, world_to_screen, get_local_axes_from_rotation, get_view_matrix
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    
    pos_data = scanner.read_mem(my_unit + mul.OFF_UNIT_X, 12)
    rot_data = scanner.read_mem(my_unit + mul.OFF_UNIT_ROTATION, 36)
    view_matrix = get_view_matrix(scanner, base_addr)
    
    pos = struct.unpack("<fff", pos_data)
    R = struct.unpack("<9f", rot_data)
    
    print(f"Unit Pos: {pos}")
    print(f"Rotation R:\n  [{R[0]:.4f}, {R[1]:.4f}, {R[2]:.4f}]\n  [{R[3]:.4f}, {R[4]:.4f}, {R[5]:.4f}]\n  [{R[6]:.4f}, {R[7]:.4f}, {R[8]:.4f}]")
    
    ax, ay, az = get_local_axes_from_rotation(R, False)
    print(f"Local axes:\n  ax (X): {ax}\n  ay (Y): {ay}\n  az (Z): {az}")
    
    # Test barrel transform
    b_data = get_weapon_barrel(scanner, my_unit, pos, R, should_log=True)
    print(f"\nBarrel World Start: {b_data[0]}")
    print(f"Barrel World End:   {b_data[1]}")
    
    # World to screen
    scr1 = world_to_screen(view_matrix, b_data[0][0], b_data[0][1], b_data[0][2], 1920, 1080)
    scr2 = world_to_screen(view_matrix, b_data[1][0], b_data[1][1], b_data[1][2], 1920, 1080)
    print(f"Screen Start: {scr1}")
    print(f"Screen End:   {scr2}")

if __name__ == '__main__':
    main()
