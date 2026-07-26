import sys, os, struct, math
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_weapon_barrel, is_valid_ptr, get_unit_3d_box_data, world_to_screen, get_view_matrix
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    
    pos_data = scanner.read_mem(my_unit + mul.OFF_UNIT_X, 12)
    pos = struct.unpack("<fff", pos_data)
    
    view_matrix = get_view_matrix(scanner, base_addr)
    print(f"View Matrix (16 floats): {view_matrix}")
    
    # Check world_to_screen for my_unit position
    scr_unit = world_to_screen(view_matrix, pos[0], pos[1], pos[2], 1920, 1080)
    print(f"My Unit Screen Pos: {scr_unit}")
    
    # Check world_to_screen for unit + 1m up
    scr_up = world_to_screen(view_matrix, pos[0], pos[1] + 1.0, pos[2], 1920, 1080)
    print(f"My Unit +1m UP Screen Pos: {scr_up}")

if __name__ == '__main__':
    main()
