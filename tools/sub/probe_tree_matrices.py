import sys, os, struct, math
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import is_valid_ptr
from src.utils import mul

def main():
    base_addr = get_game_base_address(get_game_pid())
    scanner = MemoryScanner(get_game_pid())
    init_dynamic_offsets(scanner, base_addr)
    res = mul.get_local_team(scanner, base_addr)
    my_unit = res[0]
    
    print(f"My Unit: {hex(my_unit)}")
    for off in [0x238, 0x1F0, 0x1FD8, 0x2E20, 0x2F38, 0x1E8, 0x1E0, 0x1D8, 0x200, 0x210, 0x228, 0x1C8, 0x3E8, 0x400, 0x13B0]:
        raw_ptr = scanner.read_mem(my_unit + off, 8)
        if not raw_ptr: continue
        tree_ptr = struct.unpack("<Q", raw_ptr)[0]
        if not is_valid_ptr(tree_ptr): continue
        
        # Read offsets 0x00 to 0x50 at tree_ptr
        ptrs = []
        for p_off in range(0, 0x60, 8):
            p_raw = scanner.read_mem(tree_ptr + p_off, 8)
            p_val = struct.unpack("<Q", p_raw)[0] if p_raw else 0
            ptrs.append(f"+{hex(p_off)}={hex(p_val)}")
            
        print(f"\nTree at off {hex(off)} ({hex(tree_ptr)}):")
        print("  " + " | ".join(ptrs[:4]))
        print("  " + " | ".join(ptrs[4:]))

if __name__ == '__main__':
    main()
