import struct
import math
import os

from .mul import *

def auto_find_unit_velocity(scanner, u_ptr):
    if u_ptr == 0: return

    data_unit = scanner.read_mem(u_ptr, 0x2500)
    if not data_unit: return

    # 1. สแกนหาความเร็วที่ซ่อนอยู่ใน Pointer (แบบคลาสสิกของ WT)
    for i in range(0, len(data_unit) - 8, 8):
        possible_ptr = struct.unpack_from("<Q", data_unit, i)[0]
        if is_valid_ptr(possible_ptr):
            # อ่านข้อมูลให้ลึกขึ้นเป็น 0x400
            data_mov = scanner.read_mem(possible_ptr, 0x400)
            if not data_mov: continue
            
            for j in range(0, len(data_mov) - 12, 4):
                vx, vy, vz = struct.unpack_from("<fff", data_mov, j)
                if math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz):
                    speed = math.sqrt(vx*vx + vy*vy + vz*vz)
                    # ถ้ารถวิ่งด้วยความเร็ว 2 ถึง 100 เมตร/วินาที (ประมาณ 7-360 กม./ชม.)
                    if 2.0 < speed < 100.0:
                        print(f"🎯 [POINTER] เจอความเร็ว! -> Pointer Offset: {hex(i)} | Vel Offset: {hex(j)} | ความเร็ว: {speed:.1f} m/s")

    # 2. สแกนหาความเร็วที่ฝังอยู่ในรถถังตรงๆ (ไม่มี Pointer)
    for i in range(0, len(data_unit) - 12, 4):
        vx, vy, vz = struct.unpack_from("<fff", data_unit, i)
        if math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz):
            speed = math.sqrt(vx*vx + vy*vy + vz*vz)
            # ป้องกันการไปจับโดนพิกัดแผนที่ (ซึ่งมักจะค่าสูงกว่าความเร็ว)
            if 2.0 < speed < 100.0 and abs(vx) < 150 and abs(vy) < 150 and abs(vz) < 150:
                print(f"🎯 [DIRECT] เจอความเร็วฝังตรง! -> Offset: {hex(i)} | ความเร็ว: {speed:.1f} m/s")



def auto_find_unit_velocity(scanner, u_ptr):
    if u_ptr == 0: return

    # ดึงข้อมูลตัวถังรถทั้งหมดมา 0x2500 bytes (เผื่อมันซ่อนลึก)
    data_unit = scanner.read_mem(u_ptr, 0x2500)
    if not data_unit: return

    # สแกนหา Pointer ที่ชี้ไปยังข้อมูลฟิสิกส์การเคลื่อนที่
    for i in range(0, len(data_unit) - 8, 8):
        possible_ptr = struct.unpack_from("<Q", data_unit, i)[0]
        
        # ถ้ามันเป็น Pointer (มีค่า Memory Address ที่ถูกต้อง)
        if 0x10000 < possible_ptr < 0xFFFFFFFFFFFFFFFF:
            data_mov = scanner.read_mem(possible_ptr, 0x400)
            if not data_mov: continue
            
            # เจาะเข้าไปสแกนหาตัวเลข Float 3 ตัว (Vx, Vy, Vz)
            for j in range(0, len(data_mov) - 12, 4):
                vx, vy, vz = struct.unpack_from("<fff", data_mov, j)
                if math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz):
                    speed = math.sqrt(vx*vx + vy*vy + vz*vz)
                    
                    # 🎯 เงื่อนไข: ถ้ารถวิ่งด้วยความเร็ว 3 ถึง 50 เมตร/วินาที (ประมาณ 10-180 กม./ชม.)
                    if 3.0 < speed < 50.0 and abs(vy) < 15.0: # แกน Y (ความสูง) ต้องไม่กระโดดเว่อร์
                        print(f"🚀 เจอพิกัดความเร็ว! -> Movement Pointer: [ {hex(i)} ] | Velocity Offset: [ {hex(j)} ] | ความเร็ว: {speed:.1f} m/s")