import sys, os, struct, math, time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_weapon_barrel, is_valid_ptr, get_unit_3d_box_data, world_to_screen, get_view_matrix, get_all_units, get_cgame_base
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    cgame_base = get_cgame_base(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    
    view_matrix = get_view_matrix(scanner, cgame_base)
    if not view_matrix:
        print(f"Failed to read view_matrix (cgame_base={hex(cgame_base)})!")
        return

    units = get_all_units(scanner, base_addr)
    print(f"Found {len(units)} total units.")
    
    for u_data in units:
        u_ptr = u_data[0] if isinstance(u_data, (list, tuple)) else u_data
        if u_ptr == 0 or u_ptr == my_unit: continue
        
        box_data = get_unit_3d_box_data(scanner, u_ptr, False)
        if not box_data: continue
        
        pos, bmin, bmax, R = box_data
        barrel_data = get_weapon_barrel(scanner, u_ptr, pos, R, should_log=False)
        
        # Screen position of unit
        u_scr = world_to_screen(view_matrix, pos[0], pos[1], pos[2], 1920, 1080)
        
        if barrel_data:
            b_base, b_tip = barrel_data
            p1_scr = world_to_screen(view_matrix, b_base[0], b_base[1], b_base[2], 1920, 1080)
            p2_scr = world_to_screen(view_matrix, b_tip[0], b_tip[1], b_tip[2], 1920, 1080)
            print(f"\n[Unit {hex(u_ptr)}] Pos screen: ({u_scr[0]:.1f}, {u_scr[1]:.1f})" if u_scr else f"\n[Unit {hex(u_ptr)}] Pos screen: OFFSCREEN")
            print(f"  Barrel Base: ({b_base[0]:.1f}, {b_base[1]:.1f}, {b_base[2]:.1f}) -> Screen: ({p1_scr[0]:.1f}, {p1_scr[1]:.1f})" if p1_scr else f"  Barrel Base: ({b_base[0]:.1f}, {b_base[1]:.1f}, {b_base[2]:.1f}) -> Screen: OFFSCREEN")
            print(f"  Barrel Tip:  ({b_tip[0]:.1f}, {b_tip[1]:.1f}, {b_tip[2]:.1f}) -> Screen: ({p2_scr[0]:.1f}, {p2_scr[1]:.1f})" if p2_scr else f"  Barrel Tip:  ({b_tip[0]:.1f}, {b_tip[1]:.1f}, {b_tip[2]:.1f}) -> Screen: OFFSCREEN")
        else:
            print(f"\n[Unit {hex(u_ptr)}] Barrel: NONE (Pos screen: ({u_scr[0]:.1f}, {u_scr[1]:.1f})" if u_scr else f"\n[Unit {hex(u_ptr)}] Barrel: NONE (Pos screen: OFFSCREEN)")

if __name__ == '__main__':
    main()
