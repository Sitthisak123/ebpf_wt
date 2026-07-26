import sys, os, struct, math, time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_weapon_barrel, is_valid_ptr, get_unit_3d_box_data
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    print(f"My Unit: {hex(my_unit)}")
    
    # Get AnimChar tree
    for off in [0x238, 0x1F0, 0x1FD8, 0x2E20]:
        raw_ptr = scanner.read_mem(my_unit + off, 8)
        if not raw_ptr: continue
        tree_ptr = struct.unpack("<Q", raw_ptr)[0]
        if not is_valid_ptr(tree_ptr): continue
        
        # Check WTM pointer at +0x10 and local matrix at +0x00
        wtm_raw = scanner.read_mem(tree_ptr + 0x10, 8)
        local_raw = scanner.read_mem(tree_ptr + 0x00, 8)
        
        if wtm_raw and local_raw:
            wtm_ptr = struct.unpack("<Q", wtm_raw)[0]
            loc_ptr = struct.unpack("<Q", local_raw)[0]
            print(f"Tree {hex(off)}: WTM_PTR={hex(wtm_ptr)} LOC_PTR={hex(loc_ptr)}")
            
            # Find bone_gun / bone_gun_barrel idx
            barrel_data = get_weapon_barrel(scanner, my_unit, (0,0,0), (1,0,0,0,1,0,0,0,1), should_log=True)
            cache = scanner.bone_cache.get(my_unit)
            if cache:
                idx = cache['bone_idx']
                print(f"Cached bone_idx={idx}")
                
                # Read 64 bytes from WTM and Local
                wtm_mat = scanner.read_mem(wtm_ptr + idx * 64, 64)
                loc_mat = scanner.read_mem(loc_ptr + idx * 64, 64)
                
                if wtm_mat:
                    row0 = struct.unpack_from("<ffff", wtm_mat, 0x00)
                    row1 = struct.unpack_from("<ffff", wtm_mat, 0x10)
                    row2 = struct.unpack_from("<ffff", wtm_mat, 0x20)
                    row3 = struct.unpack_from("<ffff", wtm_mat, 0x30)
                    print("\n--- WTM MATRIX ---")
                    print(f"Row0 (0x00): {row0[0]:.4f}, {row0[1]:.4f}, {row0[2]:.4f}, {row0[3]:.4f}")
                    print(f"Row1 (0x10): {row1[0]:.4f}, {row1[1]:.4f}, {row1[2]:.4f}, {row1[3]:.4f}")
                    print(f"Row2 (0x20): {row2[0]:.4f}, {row2[1]:.4f}, {row2[2]:.4f}, {row2[3]:.4f}")
                    print(f"Row3 (0x30): {row3[0]:.4f}, {row3[1]:.4f}, {row3[2]:.4f}, {row3[3]:.4f}")
                    
                if loc_mat:
                    row0 = struct.unpack_from("<ffff", loc_mat, 0x00)
                    row1 = struct.unpack_from("<ffff", loc_mat, 0x10)
                    row2 = struct.unpack_from("<ffff", loc_mat, 0x20)
                    row3 = struct.unpack_from("<ffff", loc_mat, 0x30)
                    print("\n--- LOCAL MATRIX ---")
                    print(f"Row0 (0x00): {row0[0]:.4f}, {row0[1]:.4f}, {row0[2]:.4f}, {row0[3]:.4f}")
                    print(f"Row1 (0x10): {row1[0]:.4f}, {row1[1]:.4f}, {row1[2]:.4f}, {row1[3]:.4f}")
                    print(f"Row2 (0x20): {row2[0]:.4f}, {row2[1]:.4f}, {row2[2]:.4f}, {row2[3]:.4f}")
                    print(f"Row3 (0x30): {row3[0]:.4f}, {row3[1]:.4f}, {row3[2]:.4f}, {row3[3]:.4f}")
            break

if __name__ == '__main__':
    main()
