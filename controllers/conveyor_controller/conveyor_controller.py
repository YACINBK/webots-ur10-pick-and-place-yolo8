"""
Conveyor Belt Controller for YOLOv8 Pick-and-Place System

Translated from conveyor_belt.c
Handles:
- Belt motor control
- Distance sensor monitoring
- Communication with camera and arm controllers (String format)
- Stop/resume logic for object positioning
"""

from controller import Robot
import sys


class ConveyorController:
    def __init__(self, speed=0.2, timer=0.0):
        self.robot = Robot()
        self.timestep = int(self.robot.getBasicTimeStep())
        
        # Motor setup
        self.belt_motor = self.robot.getDevice("belt_motor")
        self.belt_motor.setPosition(float('inf'))
        self.belt_motor.setVelocity(speed)
        
        # Distance sensors
        self.ds1 = self.robot.getDevice("ds1")
        self.ds2 = self.robot.getDevice("ds2")
        self.ds3 = self.robot.getDevice("ds3")
        
        self.ds1.enable(self.timestep)
        self.ds2.enable(self.timestep)
        if self.ds3:
            self.ds3.enable(self.timestep)
        
        # Communication devices
        self.emitter = self.robot.getDevice("emitter")  # To camera
        self.arm_emitter = self.robot.getDevice("arm_emitter")  # To arm (for GO_DOWN)
        
        self.receiver = self.robot.getDevice("receiver")  # From camera
        self.receiver.enable(self.timestep)
        
        self.arm_receiver = self.robot.getDevice("arm_receiver")  # From arm
        self.arm_receiver.enable(self.timestep)
        
        # State variables
        self.speed = speed
        self.timer = timer
        self.threshold = 800.0
        self.threshold3 = 800.0
        self.stop_duration = 2.0
        
        self.flag = 0
        self.stop_start_time = -1.0
        self.go_down_sent = False
    
    def run(self):
        print(f"Conveyor controller started. Speed={self.speed}, Timer={self.timer}")
        
        while self.robot.step(self.timestep) != -1:
            # Read sensors
            distance1 = self.ds1.getValue()
            distance2 = self.ds2.getValue()
            distance3 = self.ds3.getValue() if self.ds3 else 1000.0
            current_time = self.robot.getTime()
            
            # --- Handle messages from arm ---
            if self.arm_receiver.getQueueLength() > 0:
                message = self.arm_receiver.getString()
                if message == "START_CONV":
                    self.belt_motor.setVelocity(self.speed)
                self.arm_receiver.nextPacket()
            
            # --- Stop/Resume Logic ---
            if distance1 < self.threshold and self.flag == 0:
                self.belt_motor.setVelocity(0.0)
                self.stop_start_time = current_time
                self.flag = 1
                # Send STOP to camera as string
                self.emitter.send("STOP".encode('utf-8'))
                print("[Conveyor] STOP sent to camera")
            
            if self.flag == 1 and current_time - self.stop_start_time >= self.stop_duration:
                self.belt_motor.setVelocity(self.speed)
            
            if self.flag == 1 and distance2 < self.threshold:
                self.flag = 0
                self.stop_start_time = -1.0
            
            # --- GO_DOWN Signal Logic ---
            if self.ds3 and not self.go_down_sent and distance3 < self.threshold3:
                self.belt_motor.setVelocity(0.0)
                # Send GO_DOWN signal to arm as string "1"
                self.arm_emitter.send("1".encode('utf-8'))
                print("[Conveyor] GO_DOWN signal sent to arm")
                self.go_down_sent = True
            
            # Reset go_down_sent after belt resumes
            if self.go_down_sent and self.belt_motor.getVelocity() == self.speed:
                self.go_down_sent = False
            
            # --- Timer Logic ---
            if self.timer > 0 and current_time >= self.timer:
                self.belt_motor.setVelocity(0.0)
                break
        
        print("[Conveyor] Controller stopped")


if __name__ == "__main__":
    speed, timer = 0.2, 0.0
    if len(sys.argv) >= 2 and sys.argv[1] != "":
        speed = float(sys.argv[1])
    if len(sys.argv) >= 3 and sys.argv[2] != "":
        timer = float(sys.argv[2])
    
    controller = ConveyorController(speed, timer)
    controller.run()
