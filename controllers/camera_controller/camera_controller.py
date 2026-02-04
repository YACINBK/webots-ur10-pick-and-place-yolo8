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
        self.detection_timeout = 5.0  # seconds
        self.max_detection_retries = 3
    
    def connect_to_yolo_server(self):
        """Establish TCP connection to YOLO server"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.connect(('127.0.0.1', 5050))
                print("Connected to YOLO server")
                return
            except Exception as e:
                print(f"Error connecting to YOLO server (attempt {attempt + 1}/{max_retries}): {e}")
                if self.sock:
                    try:
                        self.sock.close()
                    except:
                        pass
                    self.sock = None
                if attempt < max_retries - 1:
                    import time
                    time.sleep(1)
        print("Failed to connect to YOLO server after all retries. Make sure yolo_server.py is running!")
    
    def send_image_to_yolo(self):
        """
        Capture camera image and send to YOLO server
        Returns: angle in degrees from YOLO detection
        """
        if not self.sock:
            print("Warning: No connection to YOLO server")
            return -999.0
            
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
            print("Attempting to reconnect...")
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
            self.connect_to_yolo_server()
            return -999.0
    
    def run(self):
        print("Camera controller started. Waiting for STOP signal...")
        
        while self.robot.step(self.timestep) != -1:
            if self.receiver.getQueueLength() > 0:
                message = self.receiver.getString()
                
                if message == "STOP":
                    print("STOP signal received from conveyor - initiating detection sequence")
                    
                    # Try detection with multiple attempts
                    detection_successful = False
                    for attempt in range(self.max_detection_retries):
                        print(f"Detection attempt {attempt + 1}/{self.max_detection_retries}")
                        
                        # Wait longer for recognition buffer to populate
                        num_objects = 0
                        for _ in range(10):  # Increased from 5 to 10 steps
                            num_objects = self.camera.getRecognitionNumberOfObjects()
                            if num_objects > 0:
                                break
                            self.robot.step(self.timestep)
                        
                        # Try YOLO detection
                        angle_deg = self.send_image_to_yolo()
                        
                        if num_objects > 0:
                            objects = self.camera.getRecognitionObjects()
                            obj = objects[0]
                            pos = obj.getPosition()
                            
                            # Convert angle to radians
                            angle_rad = 0.0
                            if angle_deg != -999.0:
                                angle_rad = angle_deg * math.pi / 180.0
                            else:
                                print("Warning: YOLO detection failed, using default angle 0")
                            
                            # Prepare data packet as string: "x y z angle_rad"
                            message = f"{pos[0]} {pos[1]} {pos[2]} {angle_rad}"
                            self.emitter.send(message.encode('utf-8'))
                            
                            print(f"SENT TO ARM → x={pos[0]:.3f} y={pos[1]:.3f} z={pos[2]:.3f} angle(rad)={angle_rad:.3f}")
                            detection_successful = True
                            break
                        else:
                            print(f"Warning: No objects detected by camera recognition on attempt {attempt + 1}")
                            if attempt < self.max_detection_retries - 1:
                                # Wait before retry
                                for _ in range(5):
                                    self.robot.step(self.timestep)
                    
                    if not detection_successful:
                        print("ERROR: Detection failed after all retries. Sending abort signal to reset system.")
                        # Send a special "ABORT" message or null position to signal failure
                        # This prevents the arm from hanging indefinitely
                        abort_message = "0.0 0.0 0.0 0.0"
                        self.emitter.send(abort_message.encode('utf-8'))
                        print("ABORT signal sent to arm to reset state")
                
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
