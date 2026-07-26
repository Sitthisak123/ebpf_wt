import sys, os, struct
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
    
    for off in [0x238, 0x1F0]:
        raw_ptr = scanner.read_mem(my_unit + off, 8)
        if not raw_ptr: continue
        tree_ptr = struct.unpack("<Q", raw_ptr)[0]
        if not is_valid_ptr(tree_ptr): continue
        
        raw_name = scanner.read_mem(tree_ptr + 0x40, 8)
        if not raw_name: continue
        name_ptr = struct.unpack("<Q", raw_name)[0]
        if not is_valid_ptr(name_ptr): continue
        names_block = scanner.read_mem(name_ptr, 0x4000)
        if not names_block: continue
        
        print(f"\n=== BARREL SEARCH IN TREE {hex(off)} ===")
        for i in range(400):
            try:
                str_offset = struct.unpack_from("<H", names_block, i * 2)[0]
                if str_offset == 0 or str_offset >= len(names_block): continue
                end_idx = names_block.find(b'\x00', str_offset)
                if end_idx != -1:
                    bone_name = names_block[str_offset:end_idx].decode('utf-8', errors='ignore').strip()
                    if "barrel" in bone_name.lower():
                        print(f"  FOUND BARREL BONE! idx {i:3d}: '{bone_name}'")
            except: pass

if __name__ == '__main__':
    main()
