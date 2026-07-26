import sys, os, struct, math
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_weapon_barrel, is_valid_ptr
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    print(f"My Unit: {hex(my_unit)}")
    
    pos_raw = scanner.read_mem(my_unit + mul.OFF_UNIT_X, 12)
    rot_raw = scanner.read_mem(my_unit + mul.OFF_UNIT_ROTATION, 36)
    
    if pos_raw and rot_raw:
        pos = struct.unpack('<fff', pos_raw)
        rot = struct.unpack('<fffffffff', rot_raw)
        print(f"Unit pos: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})")
        
        print("\n--- Test 1: First call (fresh scan) ---")
        res = get_weapon_barrel(scanner, my_unit, pos, rot, should_log=True)
        print(f"Result: {res}")
        
        print("\n--- Test 2: Cached call ---")
        res = get_weapon_barrel(scanner, my_unit, pos, rot, should_log=True)
        print(f"Result: {res}")
        
if __name__ == '__main__':
    main()
