# 📌 Kinematics & Velocity Tickrate Scanning Reminder
> บันทึกช่วยจำและข้อสรุปทางเทคนิคเรื่อง Offset ความเร็ว (Velocity) และ Tick Rate: My Unit vs Target Unit

---

### ❓ ทำไมก่อนหน้านี้ Target ถึง Tick Rate ไม่ขึ้น (0.0 - 0.3 Hz)?

1. **`0x0D48` / `0x0D50` (DOUBLE vec3 ~57.5 Hz) เป็น Local Player Physics Buffer เท่านั้น:**
   - ตัวเกม War Thunder ฝั่ง Client จะรันการจำลองฟิสิกส์เต็มรูปแบบ (Physics Engine 60Hz) เฉพาะ **เครื่องที่เราบังคับเอง (`My Unit` / `DAT_CONTROLLED`)** บนเครื่องเราเท่านั้น
   - สำหรับเครื่องบินลำอื่น (Bot / ศัตรู / เพื่อนร่วมทีม) เอนจินบนเครื่องเราจะไม่มีการคำนวณฟิสิกส์ให้พวกมัน ดังนั้น Pointer ที่ `u_ptr + 0x0D48` ของลำอื่นจึงเป็น Null (`0x0`) หรือเป็นบัฟเฟอร์ค้างที่ไม่มีการอัปเดต ทำให้เมื่ออ่านจะได้ **0 ticks (0.0 Hz)** เสมอ

2. **`0x0018` $\rightarrow$ `0x0318` (FLOAT vec3) เป็นเพียง Network Replication Buffer:**
   - ข้อมูลของเครื่องบินลำอื่นส่งมาจาก Server ผ่านแพ็กเกจเน็ตเวิร์ก ซึ่งเซิร์ฟเวอร์จะส่งอัปเดตมาที่ความถี่ต่ำ (ประมาณ 10–20 Hz หรือน้อยกว่านั้นเมื่ออยู่ไกล หรือเมื่อเครื่องบินกำลังบินตรงๆ ค่าเวกเตอร์แทบไม่เปลี่ยน)
   - Offset `0x0318` อาจเป็นแค่ Base velocity ที่ไม่ได้อัปเดตทุกเฟรม ทำให้สคริปต์ตรวจจับการเปลี่ยนแปลงได้เพียง **0.1 – 0.3 Hz** (กระตุกหรือแทบหยุดนิ่ง)

3. **การสแกนเครื่องบินที่จอดอยู่บนพื้น (Parked / Speed = 0 km/h):**
   - หากยูนิตเป้าหมายจอดนิ่งอยู่บนรันเวย์หรือจุดเกิด ความเร็วจริง ($\Delta Pos / \Delta t$) จะเป็น 0 km/h ตลอดเวลา ทำให้เวกเตอร์ใน Memory ไม่มีการเปลี่ยนแปลงค่า ($Ticks = 0$)

---

### 🏆 วิธีแก้ไขและการค้นพบ High-Tick Velocity สำหรับ Target (39.0 - 43.0 Hz)

จากการใช้ Deep Memory Scan บนตัวเครื่องบินเป้าหมายโดยตรง (`tools/sub/vel/scan/07_target_velocity_deep_scanner.py`):

1. **`move_ptr = 0x24C0` $\rightarrow$ `vel = 0x0E90` (FLOAT vec3) ⭐ [UNIVERSAL HIGH-TICK]**
   - **บน My Unit:** Tick Rate **`46.0 Hz`** (92 ticks)
   - **บน Target Unit:** Tick Rate **`39.0 Hz`** (117 ticks ใน 3 วินาที)
   - ขนาดความเร็วตรงกับความเร็วเคลื่อนที่ทางกายภาพจริง ($\Delta Pos / \Delta t$) อย่างแม่นยำ (ทดสอบจริง: 406.5 km/h vs 397.0 km/h)
   - **เป็น Pointer สากลที่ใช้ได้ทั้งเครื่องเราและเครื่องเป้าหมาย!**

2. **`move_ptr = 0x20F0` $\rightarrow$ `vel = 0x07C0` / `0x0CF0` (FLOAT vec3)**
   - บน Target Unit ได้ Tick Rate สูงถึง **`41.0 Hz`** (ความเร็ว 406.5 km/h)

3. **`move_ptr = 0x14B8` $\rightarrow$ `vel = 0x0F48` (FLOAT vec3)**
   - บน Target Unit ได้ Tick Rate สูงถึง **`43.0 Hz`** (ความเร็ว 360.0 km/h)

---

### 📋 สรุปตารางการเลือกใช้งาน (Best Practice Table)

| หมวดยูนิต | Move Offset | Vel Offset | Data Type | Tick Rate ที่วัดได้ | หมายเหตุ / ลักษณะการใช้งาน |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **My Unit (Local)** | `0x0D48` (หรือ `0x0D50`) | `0x0068` | **DOUBLE** | **~57.5 Hz** | Local Physics Simulation เต็มรูปแบบ (แม่นยำสูงสุดสำหรับผู้เล่น) |
| **My Unit (Alt)** | `0x24C0` | `0x0E90` | **FLOAT** | **~46.0 Hz** | High-Tick Float Vector ของผู้เล่น |
| **Target Unit (แนะนำ ⭐)** | `0x24C0` | `0x0E90` | **FLOAT** | **~39.0 Hz** | **Universal High-Tick** ใช้ได้ทั้งเป้าหมายและผู้เล่น |
| **Target Unit (Alt 1)** | `0x20F0` | `0x07C0` / `0x0CF0` | **FLOAT** | **~41.0 Hz** | Target High-Tick Interpolation Vector |
| **Target Unit (Alt 2)** | `0x14B8` | `0x0F48` | **FLOAT** | **~43.0 Hz** | Target High-Tick Buffer |
| **Target Unit (Legacy Net)** | `0x0018` | `0x0318` | **FLOAT** | 0.1 - 5.5 Hz | Network Replication แบบเดิม (ความถี่ต่ำ) |

---

### 🌪️ Smart Target Omega & Turning Prediction Scanner (`09_target_omega_smart_scanner.py`)
- เครื่องมือสแกนหา Offset ความเร็วเชิงมุม (Omega) และตรวจสอบความแม่นยำในการทำนายการเลี้ยว (Predict Turning):
  1. วัด Ground-Truth Turning ($\vec{a}_{turn} = d\vec{v}/dt$ และ $\vec{\omega}_{true} = \frac{\vec{v} \times \vec{a}}{v^2}$) จากพิกัด Position โดยตรง
  2. สแกน Memory Pointer ทั้งหมดของเป้าหมาย และทดสอบทำนายการเลี้ยว ($\vec{a}_{pred} = \vec{\omega} \times \vec{v}$) เทียบกับ $\vec{a}_{turn}$ จริง
  3. วัดคะแนน Cosine Similarity และตรวจสอบการสลับเครื่องหมาย (Transposition Bug) ของ Rotation Matrix `0x0D14`


