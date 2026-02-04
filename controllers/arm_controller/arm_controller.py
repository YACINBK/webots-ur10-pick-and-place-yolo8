"""
Arm Controller for YOLOv8 Pick-and-Place System

Translated from armtest_controller.c (Carbon Copy)
Handles:
- State machine for pick-and-place operations
- 2D planar inverse kinematics (move_horiz, move_vert)
- UR10e motor control (shoulder, lift, elbow, wrists)
- Robotiq 3-finger gripper control
- Position and angle reception from camera (Receiver, string format)
- GO_DOWN signal from conveyor (conv_receiver, string format)
"""

from controller import Robot
from enum import Enum
import numpy as np
import struct
import sys
import math


class State(Enum):
    WAITING = 0
    TRANSLATING = 1
    WAITING2 = 2
    DESCENDING = 3
    GRASPING = 4
    ASCENDING = 5
    TRANSLATING_BACK = 6
    RELEASING = 7


class ArmController:
    # Kinematic constants (UR10e)
    L1 = 0.613
    L2 = 0.637
    
    # True Base positions (Matching your saved world file)
    BASE_SHOULDER_PAN = -0.7796
    BASE_SHOULDER_LIFT = -0.507
    BASE_ELBOW = 0.5072
    BASE_WRIST1 = -1.570
    BASE_WRIST2 = -1.570
    BASE_WRIST3 = 0.0
    BASE_CURV = BASE_SHOULDER_LIFT + BASE_ELBOW
    
    STEPS = 40
    TIME_STEP = 32
    
    def __init__(self, speed=1.2):
        self.robot = Robot()
        self.timestep = int(self.robot.getBasicTimeStep())
        
        # Motors
        self.shoulder_pan = self.robot.getDevice("shoulder_pan_joint")
        self.lift = self.robot.getDevice("shoulder_lift_joint")
        self.elbow = self.robot.getDevice("elbow_joint")
        self.wrist1 = self.robot.getDevice("wrist_1_joint")
        self.wrist2 = self.robot.getDevice("wrist_2_joint")
        self.wrist3 = self.robot.getDevice("wrist_3_joint")
        
        self.hand_motors = [
            self.robot.getDevice("finger_1_joint_1"),
            self.robot.getDevice("finger_2_joint_1"),
            self.robot.getDevice("finger_middle_joint_1")
        ]
        
        # Communication
        self.emitter = self.robot.getDevice("emitter")
        self.cam_receiver = self.robot.getDevice("receiver")
        self.cam_receiver.enable(self.timestep)
        
        self.conv_receiver = self.robot.getDevice("conv_receiver")
        if self.conv_receiver:
            self.conv_receiver.enable(self.timestep)
        
        # Initial coordinates for IK
        bx0 = self.L1 * math.cos(self.BASE_SHOULDER_LIFT)
        by0 = self.L1 * math.sin(self.BASE_SHOULDER_LIFT)
        self.cx0 = bx0 + self.L2 * math.cos(self.BASE_SHOULDER_LIFT + self.BASE_ELBOW)
        self.cy0 = by0 + self.L2 * math.sin(self.BASE_SHOULDER_LIFT + self.BASE_ELBOW)
        
        # Sync with world state
        self.shoulder_pan.setPosition(self.BASE_SHOULDER_PAN)
        self.lift.setPosition(self.BASE_SHOULDER_LIFT)
        self.elbow.setPosition(self.BASE_ELBOW)
        self.wrist1.setPosition(self.BASE_WRIST1)
        self.wrist2.setPosition(self.BASE_WRIST2)
        self.wrist3.setPosition(self.BASE_WRIST3)
        self.robot.step(self.timestep)
        
        # State
        self.state = State.WAITING
        self.object_x = 0.0
        self.object_angle = 0.0
        self.go_down_received = False
        self.object_detected_and_locked = False
        self.translation_back_counter = 0
        print(f"[Bras] Initialized at your saved pose. Ready.")

    def clamp(self, v):
        return max(-1.0, min(1.0, v))

    def move_horiz(self, X):
        xc = self.cx0 - X
        yc = self.cy0
        
        R = math.sqrt(xc*xc + yc*yc)
        gamma = math.atan2(yc, xc)
        num = R*R + self.L1*self.L1 - self.L2*self.L2
        den = 2.0*R*self.L1
        
        beta = math.acos(self.clamp(num / den))
        theta = gamma - beta
        
        bx = self.L1 * math.cos(theta)
        by = self.L1 * math.sin(theta)
        
        psi = math.atan2(yc - by, xc - bx)
        phi = psi - theta
        
        self.lift.setPosition(theta)
        self.elbow.setPosition(phi)
        return theta, phi

    def move_vert(self, Z):
        xc = self.cx0
        yc = self.cy0 - Z
        
        R = math.sqrt(xc*xc + yc*yc)
        gamma = math.atan2(yc, xc)
        num = R*R + self.L1*self.L1 - self.L2*self.L2
        den = 2.0*R*self.L1
        
        beta = math.acos(self.clamp(num / den))
        theta = gamma - beta
        
        bx = self.L1 * math.cos(theta)
        by = self.L1 * math.sin(theta)
        
        psi = math.atan2(yc - by, xc - bx)
        phi = psi - theta
        
        self.lift.setPosition(theta)
        self.elbow.setPosition(phi)
        return theta, phi

    def run(self):
        while self.robot.step(self.TIME_STEP) != -1:
            # --- Check camera receiver (String format) ---
            # Only accept detection data when in WAITING state to prevent feedback loops/instability
            if self.cam_receiver.getQueueLength() > 0:
                if self.state == State.WAITING:
                    data_str = self.cam_receiver.getString()
                    try:
                        pos = [float(x) for x in data_str.split()]
                        if len(pos) >= 4:
                            self.object_x = pos[1]  # Distance relative to camera
                            self.object_angle = pos[3]
                            print(f"Objet détecté en x = {self.object_x:.3f} (Angle: {self.object_angle:.2f})")
                    except ValueError:
                        print(f"Error parsing camera data: {data_str}")
                
                # Always clear the queue to avoid processing stale/accumulated packets
                while self.cam_receiver.getQueueLength() > 0:
                    self.cam_receiver.nextPacket()

            # --- Check conveyor receiver (String format) ---
            if self.conv_receiver and self.conv_receiver.getQueueLength() > 0:
                data_str = self.conv_receiver.getString()
                if data_str == "1":
                    self.go_down_received = True
                    print("[Bras] Signal GO_DOWN reçu (buffered)")
                self.conv_receiver.nextPacket()

            # --- State Machine ---
            if self.state == State.WAITING:
                if self.object_x != 0.0 and not self.object_detected_and_locked:
                    # Reset pick cycle flags
                    self.go_down_received = False
                    self.object_detected_and_locked = True # Lock out further detections until cycle complete
                    
                    # Reset IK geometry based on current BASE_POSE
                    bx0 = self.L1 * math.cos(self.BASE_SHOULDER_LIFT)
                    by0 = self.L1 * math.sin(self.BASE_SHOULDER_LIFT)
                    self.cx0 = bx0 + self.L2 * math.cos(self.BASE_SHOULDER_LIFT + self.BASE_ELBOW)
                    self.cy0 = by0 + self.L2 * math.sin(self.BASE_SHOULDER_LIFT + self.BASE_ELBOW)
                    
                    self.state = State.TRANSLATING
                    print(f"Début translation horizontal pour x = {self.object_x:.3f}")
                else:
                    self.go_down_received = False  # Keep buffer clear if no object

            elif self.state == State.TRANSLATING:
                x_start = 0.0
                x_end = -self.object_x
                
                for k in range(self.STEPS + 1):
                    s = k / self.STEPS
                    X = x_start + s * (x_end - x_start)
                    theta, phi = self.move_horiz(X)
                    
                    wrist1_cmd = self.BASE_WRIST1 + self.BASE_CURV - (theta + phi)
                    self.shoulder_pan.setPosition(self.BASE_SHOULDER_PAN)
                    self.wrist1.setPosition(wrist1_cmd)
                    self.wrist2.setPosition(self.BASE_WRIST2)
                    self.wrist3.setPosition(self.BASE_WRIST3)
                    
                    if self.robot.step(self.TIME_STEP) == -1: break
                
                self.cx0 = self.cx0 - x_end
                print("Translation horizontale terminée, bras en attente du signal de descente")
                self.state = State.WAITING2

            elif self.state == State.WAITING2:
                self.wrist3.setPosition(self.object_angle)
                # Process buffered signal
                if self.go_down_received:
                    print("[Bras] Buffered GO_DOWN detected, starting descent.")
                    self.go_down_received = False
                    self.state = State.DESCENDING

            elif self.state == State.DESCENDING:
                z_start = 0.0
                z_end = -0.37
                
                for k in range(self.STEPS + 1):
                    s = k / self.STEPS
                    Z = z_start + s * (z_end - z_start)
                    theta, phi = self.move_vert(Z)
                    
                    wrist1_cmd = self.BASE_WRIST1 + self.BASE_CURV - (theta + phi)
                    self.shoulder_pan.setPosition(self.BASE_SHOULDER_PAN)
                    self.wrist1.setPosition(wrist1_cmd)
                    self.wrist2.setPosition(self.BASE_WRIST2)
                    
                    if self.robot.step(self.TIME_STEP) == -1: break
                
                self.state = State.GRASPING
                print("[Bras] Descente terminée, saisie de la pièce")

            elif self.state == State.GRASPING:
                print("Grasping piece")
                for motor in self.hand_motors:
                    # Fix: use slightly safer position to avoid joint limit warnings
                    motor.setPosition(0.4)
                
                self.robot.step(self.TIME_STEP)
                self.state = State.ASCENDING
                print("[Bras] Pièce saisie, lancement de la remontée")

            elif self.state == State.ASCENDING:
                z_start = -0.4
                z_end = 0.0
                old_cx0, old_cy0 = self.cx0, self.cy0
                
                for k in range(self.STEPS + 1):
                    s = k / self.STEPS
                    Z = z_start + s * (z_end - z_start)
                    theta, phi = self.move_vert(Z)
                    
                    wrist1_cmd = self.BASE_WRIST1 + self.BASE_CURV - (theta + phi)
                    self.shoulder_pan.setPosition(self.BASE_SHOULDER_PAN)
                    self.wrist1.setPosition(wrist1_cmd)
                    self.wrist2.setPosition(self.BASE_WRIST2)
                    
                    if self.robot.step(self.TIME_STEP) == -1: break
                
                self.cx0, self.cy0 = old_cx0, old_cy0
                self.translation_back_counter = self.STEPS
                self.state = State.TRANSLATING_BACK
                print("[Bras] Remontée terminée, début translation arrière")

            elif self.state == State.TRANSLATING_BACK:
                x_start = -self.object_x
                x_end = 0.0
                
                if self.translation_back_counter > 0:
                    s = (self.STEPS - self.translation_back_counter) / self.STEPS
                    X = x_end - s * (x_end - x_start)
                    theta, phi = self.move_horiz(-X)
                    
                    wrist1_cmd = self.BASE_WRIST1 + self.BASE_CURV - (theta + phi)
                    self.shoulder_pan.setPosition(self.BASE_SHOULDER_PAN)
                    self.wrist1.setPosition(wrist1_cmd)
                    self.wrist2.setPosition(self.BASE_WRIST2)
                    self.wrist3.setPosition(self.BASE_WRIST3)
                    self.translation_back_counter -= 1
                else:
                    self.cx0 = x_end
                    self.object_x = 0.0
                    self.object_detected_and_locked = False # Unlock for next cycle
                    print("[Bras] Retour horizontal terminé, début relâchement")
                    self.state = State.RELEASING

            elif self.state == State.RELEASING:
                self.shoulder_pan.setPosition(self.BASE_SHOULDER_PAN - math.pi)
                for _ in range(self.STEPS):
                    self.robot.step(self.TIME_STEP)
                
                for motor in self.hand_motors:
                    motor.setPosition(0.0)
                for _ in range(10):
                    self.robot.step(self.TIME_STEP)
                
                self.shoulder_pan.setPosition(self.BASE_SHOULDER_PAN)
                for _ in range(self.STEPS):
                    self.robot.step(self.TIME_STEP)
                
                print("[Bras] Pièce relâchée, retour à l'attente")
                self.emitter.send("START_CONV".encode('utf-8'))
                self.state = State.WAITING


if __name__ == "__main__":
    speed = 1.2
    if len(sys.argv) >= 2 and sys.argv[1] != "":
        speed = float(sys.argv[1])
    
    controller = ArmController(speed)
    controller.run()
