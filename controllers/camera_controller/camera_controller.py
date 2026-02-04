"""
Camera Controller for YOLOv8 Pick-and-Place System

Translated from camera2.c
Handles:
- Camera image capture
- TCP communication with YOLO server
- Object recognition via Webots API
- Position + angle transmission to arm controller (encoded as string)
"""

import socket
import struct
import numpy as np
from controller import Robot
import math


class CameraController:
    def __init__(self):
        self.robot = Robot()
        self.timestep = 32
        
        # Camera setup
        self.camera = self.robot.getDevice("camera")
        self.camera.enable(self.timestep)
        self.camera.recognitionEnable(self.timestep)
        
        # Communication devices
        self.emitter = self.robot.getDevice("emitter")
        self.receiver = self.robot.getDevice("receiver")
        self.receiver.enable(self.timestep)
        
        # TCP connection to YOLO server
        self.sock = None
        self.connect_to_yolo_server()
        
        # State
        self.last_angle = -999.0
    
    def connect_to_yolo_server(self):
        """Establish TCP connection to YOLO server"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect(('127.0.0.1', 5050))
            print("Connected to YOLO server")
        except Exception as e:
            print(f"Error connecting to YOLO server: {e}")
            print("Make sure yolo_server.py is running!")
    
    def send_image_to_yolo(self):
        """
        Capture camera image and send to YOLO server
        Returns: angle in degrees from YOLO detection
        """
        w = self.camera.getWidth()
        h = self.camera.getHeight()
        img_bgra = self.camera.getImage()
        
        if not img_bgra:
            return -999.0
            
        img_np = np.frombuffer(img_bgra, dtype=np.uint8).reshape((h, w, 4))
        
        # Extract RGB channels
        buffer = np.zeros((h, w, 3), dtype=np.uint8)
        buffer[:, :, 0] = img_np[:, :, 2]  # R
        buffer[:, :, 1] = img_np[:, :, 1]  # G
        buffer[:, :, 2] = img_np[:, :, 0]  # B
        
        buffer_bytes = buffer.tobytes()
        size = len(buffer_bytes)
        
        try:
            # Send dimensions and size
            self.sock.sendall(struct.pack("!I", w))
            self.sock.sendall(struct.pack("!I", h))
            self.sock.sendall(struct.pack("!I", size))
            
            # Send image data
            self.sock.sendall(buffer_bytes)
            
            # Receive angle from YOLO
            angle_bytes = self.sock.recv(8)
            if len(angle_bytes) == 8:
                angle_deg = struct.unpack("d", angle_bytes)[0]
                self.last_angle = angle_deg
                print(f"Angle received from YOLO: {angle_deg:.2f}°")
                return angle_deg
            else:
                return -999.0
        except Exception as e:
            print(f"Error communicating with YOLO server: {e}")
            return -999.0
    
    def run(self):
        print("Camera controller started. Waiting for STOP signal...")
        
        while self.robot.step(self.timestep) != -1:
            if self.receiver.getQueueLength() > 0:
                message = self.receiver.getString()
                
                if message == "STOP":
                    print("STOP signal received from conveyor - initiating detection sequence")
                    
                    # Try detection over several steps to ensure recognition buffer is ready
                    num_objects = 0
                    for _ in range(5):
                        num_objects = self.camera.getRecognitionNumberOfObjects()
                        if num_objects > 0:
                            break
                        self.robot.step(self.timestep)
                    
                    # If internal recognition failed, still try YOLO
                    angle_deg = self.send_image_to_yolo()
                    
                    if num_objects > 0:
                        objects = self.camera.getRecognitionObjects()
                        obj = objects[0]
                        pos = obj.getPosition()
                        
                        # Convert angle to radians
                        # If YOLO failed (-999), we set angle to 0 or leave it
                        angle_rad = 0.0
                        if angle_deg != -999.0:
                            angle_rad = angle_deg * math.pi / 180.0
                        
                        # Prepare data packet as string: "x y z angle_rad"
                        # This avoids UnicodeDecodeError in arm_controller
                        message = f"{pos[0]} {pos[1]} {pos[2]} {angle_rad}"
                        self.emitter.send(message.encode('utf-8'))
                        
                        print(f"SENT TO ARM → x={pos[0]:.3f} y={pos[1]:.3f} z={pos[2]:.3f} angle(rad)={angle_rad:.3f}")
                    else:
                        print("Warning: No objects detected by camera recognition")
                
                self.receiver.nextPacket()
    
    def cleanup(self):
        if self.sock:
            self.sock.close()


if __name__ == "__main__":
    controller = CameraController()
    try:
        controller.run()
    finally:
        controller.cleanup()
