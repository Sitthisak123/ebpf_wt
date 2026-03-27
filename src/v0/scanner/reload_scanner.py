import os
import sys
import struct
import math
import time
from main import MemoryScanner, get_game_pid, get_game_base_address

# 🎯 ดึง Offsets และฟังก์ชันจาก mul.py ของแท้
from src.utils.mul import get_cgame_base, DAT_CONTROLLED_UNIT, is_valid_ptr

def main():
    print("[*] 🚀 กำลังโหลด THE SMART RELOAD SCANNER V4 (PRECISION BUILD)...")
    try:
        pid = get_game_pid()
        base_addr = get_game_base_address(pid)
        scanner = MemoryScanner(pid)
    except Exception as e:
        print(f"[-] Error: {e}")
        sys.exit(1)
        
    cgame_base = get_cgame_base(scanner, base_addr)
    if not cgame_base:
        print("[-] หา CGame ไม่เจอ...")
        return
        
    # 🎯 ใช้ DAT_CONTROLLED_UNIT ที่เรายืนยันแล้วว่าแม่นยำที่สุด
    control_addr = base_addr + (DAT_CONTROLLED_UNIT - 0x400000)
    my_unit_raw = scanner.read_mem(control_addr, 8)
    if not my_unit_raw: 
        print("[-] ไม่สามารถอ่านค่า Control Address ได้")
        return
        
    my_unit = struct.unpack("<Q", my_unit_raw)[0]
    
    if not is_valid_ptr(my_unit):
        print("[-] Pointer ของรถถังไม่ถูกต้อง กรุณาเข้า Test Drive")
        return
    
    print("="*60)
    print(f"🟢 พบรถถังของคุณที่ Address: {hex(my_unit)}")
    print("="*60)

    # ขยายการสแกนเป็น 0x3000 เพื่อให้ครอบคลุมโครงสร้างรถถังทั้งหมด
    SCAN_SIZE = 0x3000

    # ---------------------------------------------------------
    # STEP 1: Baseline (พร้อมยิง)
    # ---------------------------------------------------------
    print("\n[STEP 1]: จอดรถถังนิ่งๆ รอให้กระสุน 'โหลดเต็มพร้อมยิง'")
    input(">>> ถ้ายืนยันว่ากระสุนเต็มแล้ว ให้กด Enter เพื่อบันทึก Snapshot A... ")
    data_A = scanner.read_mem(my_unit, SCAN_SIZE) 
    print("[+] บันทึก A สำเร็จ!")

    # ---------------------------------------------------------
    # STEP 2: Noise Filter (กรองขยะ)
    # ---------------------------------------------------------
    print("\n[STEP 2]: 🛑 อย่ายิง! ห้ามขยับเมาส์! ห้ามขยับรถ! จอดนิ่งๆ ไว้เหมือนเดิม")
    input(">>> ทิ้งไว้สัก 3-4 วินาที แล้วกด Enter เพื่อบันทึก Snapshot B (ใช้กรองค่าที่แกว่ง)... ")
    data_B = scanner.read_mem(my_unit, SCAN_SIZE)
    print("[+] บันทึก B สำเร็จ!")

    # ---------------------------------------------------------
    # STEP 3: The Action (ยิงปืน)
    # ---------------------------------------------------------
    print("\n[STEP 3]: กลับเข้าเกม -> กด 'ยิงปืนหลัก' -> รีบสลับกลับมากด Enter ทันที!")
    input(">>> กด Enter เพื่อบันทึก Snapshot C (ต้องกดขณะที่หลอดยังโหลดไม่เต็ม)... ")
    data_C = scanner.read_mem(my_unit, SCAN_SIZE)
    print("[+] บันทึก C สำเร็จ!")

    # ---------------------------------------------------------
    # วิเคราะห์ผลลัพธ์ (แบบคลายกฎ)
    # ---------------------------------------------------------
    print("\n🔍 กำลังวิเคราะห์ข้อมูล (ค้นหาทั้ง Float และ Int)...")
    candidates = []
    
    for i in range(0, len(data_A) - 4, 4):
        try:
            f_A = struct.unpack("<f", data_A[i:i+4])[0]
            f_B = struct.unpack("<f", data_B[i:i+4])[0]
            f_C = struct.unpack("<f", data_C[i:i+4])[0]
            
            i_A = struct.unpack("<i", data_A[i:i+4])[0]
            i_B = struct.unpack("<i", data_B[i:i+4])[0]
            i_C = struct.unpack("<i", data_C[i:i+4])[0]
            
            # 📌 ค้นหาตัวเลขทศนิยม (Float)
            if math.isfinite(f_A) and math.isfinite(f_B) and math.isfinite(f_C):
                # กฎ: A กับ B ต้องแทบจะไม่เปลี่ยน (นิ่ง) แต่ C ต้องขยับไปเยอะพอสมควร
                if abs(f_A - f_B) <= 0.001 and abs(f_A - f_C) >= 0.05:
                    # ตัดค่าที่ใหญ่เกินจริง (เช่น พิกัดโลก) ทิ้งไป เอาแค่เลขน้อยๆ
                    if abs(f_A) <= 1000.0 and abs(f_C) <= 1000.0:
                        candidates.append((i, f"Float: {f_A:8.3f}  --->  {f_C:8.3f}"))
                        continue # ข้ามไปรอบถัดไป เพื่อไม่ให้มันเก็บซ้ำเป็น Int
                        
            # 📌 ค้นหาจำนวนเต็ม (Int)
            if i_A == i_B and i_A != i_C:
                # กรองค่า Int ขยะที่ใหญ่เป็นล้านๆ หรือเป็น Pointer ทิ้งไป
                if abs(i_A) <= 50000 and abs(i_C) <= 50000:
                    candidates.append((i, f"Int  : {i_A:<8}  --->  {i_C:<8}"))
                    
        except:
            pass

    if candidates:
        print(f"\n🎉 เจอ Offset ที่น่าสงสัยทั้งหมด {len(candidates)} จุด:")
        print(f"{'Offset':<8} | {'การเปลี่ยนแปลง (เต็ม -> เพิ่งยิง)'}")
        print("-" * 50)
        for off, desc in candidates:
            # เน้นโชว์เฉพาะระยะปลอดภัย ไม่เอาส่วนหัวและส่วนท้ายมากไป
            if 0x100 <= off <= SCAN_SIZE:
                print(f"{hex(off):<8} | {desc}")
                
        print("\n💡 คำแนะนำ: มองหา Float ที่เปลี่ยนจาก 0.000 -> 7.xxx (เวลาในการโหลด) หรือ 1.000 -> 0.000 ครับ!")
    else:
        print("\n[-] ยังไม่เจออยู่ดีครับ! (อาจจะซ่อนอยู่ใน Offset ลึกกว่านี้ หรืออยู่ใน Pointer อื่น)")

if __name__ == '__main__':
    main()