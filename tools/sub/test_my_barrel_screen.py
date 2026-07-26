import sys, os, struct, math
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_weapon_barrel, is_valid_ptr, get_unit_3d_box_data, world_to_screen, get_view_matrix, get_cgame_base
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    cgame_base = get_cgame_base(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    print(f"My Unit: {hex(my_unit)}")
    
    view_matrix = get_view_matrix(scanner, cgame_base)
    if not view_matrix:
        print("Failed to read view_matrix!")
        return

    box_data = get_unit_3d_box_data(scanner, my_unit, False)
    if not box_data:
        print("Failed to read box_data!")
        return
        
    pos, bmin, bmax, R = box_data
    barrel_data = get_weapon_barrel(scanner, my_unit, pos, R, should_log=True)
    u_scr = world_to_screen(view_matrix, pos[0], pos[1], pos[2], 1920, 1080)
    
    print(f"\nUnit Pos: {pos} -> Screen: {u_scr}")
    if barrel_data:
        b_base, b_tip = barrel_data
        p1_scr = world_to_screen(view_matrix, b_base[0], b_base[1], b_base[2], 1920, 1080)
        p2_scr = world_to_screen(view_matrix, b_tip[0], b_tip[1], b_tip[2], 1920, 1080)
        print(f"Barrel Base World: {b_base} -> Screen: {p1_scr}")
        print(f"Barrel Tip World:  {b_tip} -> Screen: {p2_scr}")

if __name__ == '__main__':
    main()
