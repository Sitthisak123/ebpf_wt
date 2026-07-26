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
    
    raw_ptr = scanner.read_mem(my_unit + 0x238, 8)
    tree_ptr = struct.unpack("<Q", raw_ptr)[0]
    raw_name = scanner.read_mem(tree_ptr + 0x40, 8)
    name_ptr = struct.unpack("<Q", raw_name)[0]
    names_block = scanner.read_mem(name_ptr, 0x4000)
    
    print("=== DUMPING ALL 400 BONE NAMES FOR 0x238 ===")
    for i in range(400):
        try:
            str_offset = struct.unpack_from("<H", names_block, i * 2)[0]
            if str_offset == 0 or str_offset >= len(names_block): continue
            end_idx = names_block.find(b'\x00', str_offset)
            if end_idx != -1:
                bname = names_block[str_offset:end_idx].decode('utf-8', errors='ignore').strip()
                print(f"[{i:3d}] {bname}")
        except: pass

if __name__ == '__main__':
    main()
