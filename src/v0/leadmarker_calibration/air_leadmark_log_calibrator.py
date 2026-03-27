import pandas as pd
import numpy as np
import math
import os
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt

# =======================================================
# ⚙️ ตั้งค่าชื่อไฟล์ Log ของท่านที่นี่
# =======================================================
LOG_FILENAME = "lead_calibration_log_1773533165.csv" # เปลี่ยนชื่อไฟล์ให้ตรงกับที่ท่านมี

def run_calibration(filename):
    if not os.path.exists(filename):
        print(f"❌ ไม่พบไฟล์ {filename} กรุณาตรวจสอบชื่อไฟล์อีกครั้ง")
        return

    print(f"📂 กำลังโหลดข้อมูลจาก: {filename}...")
    df = pd.read_csv(filename)
    
    if len(df) < 50:
        print("⚠️ ข้อมูลใน Log น้อยเกินไป (ควรมีอย่างน้อย 50 เฟรม)")
        return

    # สร้างเส้นจำลองพิกัดจริงในอนาคต (Interpolation) เพื่อให้เปรียบเทียบได้ทุกเสี้ยววินาที
    print("📈 กำลังสร้างเส้นกราฟพิกัดเป้าหมาย (Target Path Interpolation)...")
    interp_x = interp1d(df['Timestamp'], df['T_PosX'], kind='linear', fill_value='extrapolate')
    interp_y = interp1d(df['Timestamp'], df['T_PosY'], kind='linear', fill_value='extrapolate')
    interp_z = interp1d(df['Timestamp'], df['T_PosZ'], kind='linear', fill_value='extrapolate')
    max_time = df['Timestamp'].max()

    # 🎯 ฟังก์ชันจำลองการยิง (Analytical Solver)
    def simulate_prediction(row, test_decay, test_tune):
        t_x, t_y, t_z = row['T_PosX'], row['T_PosY'], row['T_PosZ']
        vx, vy, vz = row['T_VelX'], row['T_VelY'], row['T_VelZ']
        ax, ay, az = row['T_AccX'], row['T_AccY'], row['T_AccZ']
        my_x, my_y, my_z = row['My_PosX'], row['My_PosY'], row['My_PosZ']
        my_vx, my_vy, my_vz = row['My_VelX'], row['My_VelY'], row['My_VelZ']
        bullet_speed = row['Bullet_Speed']
        dist = row['Distance']
        
        # ดึงค่า Drag_K ดิบกลับมา แล้วคูณด้วย Tune ที่เราจะใช้ทดสอบ
        k_raw = row['Drag_K'] / row['Drag_Tune'] if row['Drag_Tune'] > 0 else 0.0001
        k = k_raw * test_tune
        
        best_t = dist / bullet_speed if bullet_speed > 0 else 0.1
        pure_pred_x, pure_pred_y, pure_pred_z = t_x, t_y, t_z
        
        for _ in range(4):
            if test_decay > 0 and best_t > 0:
                a_term = (test_decay * best_t - 1.0 + math.exp(-test_decay * best_t)) / (test_decay**2)
            else:
                a_term = 0.0
                
            pure_pred_x = t_x + (vx * best_t) + (ax * a_term)
            pure_pred_y = t_y + (vy * best_t) + (ay * a_term)
            pure_pred_z = t_z + (vz * best_t) + (az * a_term)
            
            dx_impact = pure_pred_x - (my_x + my_vx * best_t)
            dy_impact = pure_pred_y - (my_y + 1.5 + my_vy * best_t)
            dz_impact = pure_pred_z - (my_z + my_vz * best_t)
            dist_to_impact = math.sqrt(dx_impact**2 + dy_impact**2 + dz_impact**2)
            
            if bullet_speed > 0:
                if k > 0.000001:
                    kx = min(k * dist_to_impact, 5.0)
                    best_t = (math.exp(kx) - 1.0) / (k * bullet_speed)
                else:
                    best_t = dist_to_impact / bullet_speed
            else:
                best_t = 999.0
                
        return best_t, pure_pred_x, pure_pred_y, pure_pred_z

    # =======================================================
    # 🔬 GRID SEARCH (วิ่งหาคู่ตัวเลขที่ดีที่สุด)
    # =======================================================
    # สุ่มข้อมูลบางส่วนเพื่อไม่ให้ประมวลผลนานเกินไป (ดึงมา 1 ใน 5 เฟรม)
    sample_df = df.iloc[::5].copy() 
    
    # ขอบเขตค่าที่จะทดสอบ (ปรับแก้ได้ถ้าต้องการหาละเอียดกว่านี้)
    decays_to_test = np.arange(0.05, 0.40, 0.05)  # ทดสอบ Turn Decay ตั้งแต่ 0.05 ถึง 0.35
    tunes_to_test = np.arange(0.30, 1.20, 0.05)   # ทดสอบ Drag Tune ตั้งแต่ 0.30 ถึง 1.15
    
    print(f"🧪 เริ่มจำลองการยิง {len(decays_to_test) * len(tunes_to_test)} รูปแบบ...")
    results = []
    
    for dec in decays_to_test:
        for tune in tunes_to_test:
            errors = []
            for idx, row in sample_df.iterrows():
                t0 = row['Timestamp']
                best_t, pred_x, pred_y, pred_z = simulate_prediction(row, dec, tune)
                t_impact = t0 + best_t
                
                # เช็คเฉพาะข้อมูลที่อนาคตยังอยู่ในช่วงที่ Log บันทึกไว้
                if t_impact <= max_time - 0.5: 
                    act_x = interp_x(t_impact)
                    act_y = interp_y(t_impact)
                    act_z = interp_z(t_impact)
                    
                    # คำนวณ Error (ระยะห่างระหว่างจุดที่ยิงไป กับ จุดที่เครื่องบินอยู่จริง)
                    err = math.sqrt((pred_x - act_x)**2 + (pred_y - act_y)**2 + (pred_z - act_z)**2)
                    errors.append(err)
            
            if errors:
                mean_err = np.mean(errors)
                results.append({'Decay_Rate': dec, 'Drag_Tune': tune, 'Mean_Error': mean_err})

    # =======================================================
    # 🏆 สรุปผล
    # =======================================================
    res_df = pd.DataFrame(results)
    best_config = res_df.loc[res_df['Mean_Error'].idxmin()]
    
    print("\n" + "="*50)
    print("🎯 THE OPTIMAL CALIBRATION RESULTS 🎯")
    print("="*50)
    print(f"🏆 ค่า Turn Decay ที่ดีที่สุด     : {best_config['Decay_Rate']:.3f}")
    print(f"🏆 ค่า DRAG_TUNE ที่ดีที่สุด      : {best_config['Drag_Tune']:.3f}")
    print(f"💥 ความคลาดเคลื่อนเฉลี่ย (Error)  : {best_config['Mean_Error']:.2f} เมตร")
    print("="*50)
    
    print("\n👉 ท็อป 5 การตั้งค่าที่ดีที่สุด:")
    print(res_df.sort_values('Mean_Error').head(5).to_string(index=False))

    # (ตัวเลือกเสริม) วาดกราฟ Heatmap เพื่อดูว่าค่าตรงไหนดีที่สุด
    try:
        pivot = res_df.pivot(index='Decay_Rate', columns='Drag_Tune', values='Mean_Error')
        plt.figure(figsize=(10, 8))
        plt.imshow(pivot, cmap='coolwarm', aspect='auto', origin='lower', 
                   extent=[tunes_to_test[0], tunes_to_test[-1], decays_to_test[0], decays_to_test[-1]])
        plt.colorbar(label='Mean Error (meters)')
        plt.scatter(best_config['Drag_Tune'], best_config['Decay_Rate'], color='yellow', marker='*', s=200, label='Best Calibration')
        plt.title('Ballistic Calibration Heatmap (Lower is Better)')
        plt.xlabel('Drag Tune Multiplier')
        plt.ylabel('Turn Decay Rate')
        plt.legend()
        plt.tight_layout()
        plt.savefig('calibration_heatmap.png')
        print("\n📊 สร้างกราฟ Heatmap เสร็จสิ้น: บันทึกรูปเป็น 'calibration_heatmap.png'")
    except Exception as e:
        print(f"ไม่สามารถวาดกราฟได้: {e}")

if __name__ == "__main__":
    run_calibration(LOG_FILENAME)