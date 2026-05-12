import numpy as np
import time

class KinematicKalmanFilter:
    def __init__(self, init_pos, init_vel):
        """
        ระบบติดตามเป้าหมาย 3 มิติ (พิกัด X, Y, Z | ความเร็ว VX, VY, VZ | ความเร่ง AX, AY, AZ)
        """
        # State Vector [X, Y, Z, VX, VY, VZ, AX, AY, AZ]^T
        self.x = np.array([
            init_pos[0], init_pos[1], init_pos[2],
            init_vel[0], init_vel[1], init_vel[2],
            0.0, 0.0, 0.0
        ], dtype=float).reshape(9, 1)
        
        # P: Covariance Matrix (ความไม่แน่นอนเริ่มต้น)
        self.P = np.eye(9, dtype=float) * 100.0
        
        # H: Measurement Matrix (เราวัดค่า พิกัด 3 แกน และ ความเร็ว 3 แกน)
        self.H = np.zeros((6, 9), dtype=float)
        self.H[0:3, 0:3] = np.eye(3) # สังเกตพิกัด (Position)
        self.H[3:6, 3:6] = np.eye(3) # สังเกตความเร็ว (Velocity)
        
        # R: Measurement Noise (สัญญาณรบกวนจากการอ่าน Memory) 
        # ปรับเพิ่มตัวเลขถ้าเป้าแกว่งมาก, ปรับลดถ้าเป้านิ่งอยู่แล้ว
        self.R = np.eye(6, dtype=float)
        self.R[0:3, 0:3] *= 0.5   # ความคลาดเคลื่อนของตำแหน่ง
        self.R[3:6, 3:6] *= 2.0   # ความคลาดเคลื่อนของความเร็ว (ใส่ค่าเยอะเพราะมีความแกว่ง)
        
        self.last_time = time.time()

    def update(self, pos, vel):
        """
        อัปเดตข้อมูลและคืนค่า ตำแหน่งและความเร็ว ที่ถูกกรองจนสมูทแล้ว
        pos: (x, y, z), vel: (vx, vy, vz)
        """
        current_time = time.time()
        dt = current_time - self.last_time
        self.last_time = current_time
        
        if dt <= 0:
            dt = 0.01
            
        # ----------------------------------------------------
        # 1. PREDICT (พยากรณ์ตำแหน่งล่วงหน้าจากฟิสิกส์ Kinematic)
        # ----------------------------------------------------
        # F: State Transition Matrix
        F = np.eye(9, dtype=float)
        
        # Pos = Pos + Vel*dt + 0.5*Acc*dt^2
        for i in range(3):
            F[i, i+3] = dt
            F[i, i+6] = 0.5 * dt**2
            
        # Vel = Vel + Acc*dt
        for i in range(3):
            F[i+3, i+6] = dt
            
        # Q: Process Noise (โอกาสที่เป้าหมายจะหักเลี้ยว/เปลี่ยนความเร่ง)
        # ยิ่งค่าน้อย แปลว่าเราเชื่อว่าเครื่องบินบินตรงๆ, ยิ่งเยอะ แปลว่ามันกำลัง Dogfight
        accel_variance = 15.0 # ปรับความกระชากของการเลี้ยว
        Q = np.zeros((9, 9), dtype=float)
        for i in range(3):
            Q[i, i] = (dt**5 / 20) * accel_variance
            Q[i, i+3] = (dt**4 / 8) * accel_variance
            Q[i, i+6] = (dt**3 / 6) * accel_variance
            Q[i+3, i] = Q[i, i+3]
            Q[i+3, i+3] = (dt**3 / 3) * accel_variance
            Q[i+3, i+6] = (dt**2 / 2) * accel_variance
            Q[i+6, i] = Q[i, i+6]
            Q[i+6, i+3] = Q[i+3, i+6]
            Q[i+6, i+6] = dt * accel_variance
            
        # ทำนาย State ล่วงหน้า
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q
        
        # ----------------------------------------------------
        # 2. UPDATE (แก้ไขคำทำนายด้วยข้อมูลที่เพิ่งอ่านจาก Memory)
        # ----------------------------------------------------
        z = np.array([
            pos[0], pos[1], pos[2],
            vel[0], vel[1], vel[2]
        ]).reshape(6, 1)
        
        y = z - (self.H @ self.x)             # ค่าความคลาดเคลื่อน (Error)
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S) # Kalman Gain
        
        self.x = self.x + (K @ y)
        self.P = (np.eye(9) - K @ self.H) @ self.P
        
        # ส่งค่าที่สมูทแล้วกลับไปใช้งาน
        smoothed_pos = (self.x[0,0], self.x[1,0], self.x[2,0])
        smoothed_vel = (self.x[3,0], self.x[4,0], self.x[5,0])
        smoothed_acc = (self.x[6,0], self.x[7,0], self.x[8,0]) # ความเร่ง (ใช้ประยุกต์ทำ Advance Lead ได้)
        
        return smoothed_pos, smoothed_vel, smoothed_acc