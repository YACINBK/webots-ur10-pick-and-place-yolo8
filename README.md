# YOLOv8 Pick-and-Place Migration Project

This project is a **direct Python translation** of the C-based UR10e pick-and-place system with YOLOv8 object detection.

## Project Structure

```
yolo-migration/
├── controllers/
│   ├── camera_controller.py       # Camera + YOLO TCP client
│   ├── arm_controller.py          # State machine + IK
│   └── conveyor_controller.py     # Belt automation
├── yolo_server/
│   ├── yolo_server.py             # YOLOv8 detection server
│   └── best.pt                    # YOLO model weights
├── worlds/
│   └── yolo_migration.wbt         # Webots world file
└── README.md                      # This file
```

## Setup Instructions

### 1. Python Dependencies

Install required packages:
```bash
pip install numpy ultralytics opencv-python
```

### 2. Start YOLO Server

**Important**: The YOLO server must be running **before** starting the Webots simulation.

```bash
cd yolo_server
python yolo_server.py
```

You should see:
```
Serveur YOLO démarré. En attente de Webots...
```

### 3. Open Webots World

1. Open Webots
2. Load `worlds/yolo_migration.wbt`
3. The simulation will start automatically

## How It Works

### Communication Flow

```
Conveyor Belt (ds1) → Camera → YOLO Server → Camera → Arm
         ↓                                              ↓
    (STOP signal)                              (Position + Angle)
                                                        ↓
                                                  Pick & Place
                                                        ↓
                                              Arm → Conveyor Belt
                                                  (START_CONV signal)
```

### State Machine (Arm Controller)

1. **WAITING**: Wait for position data from camera
2. **TRANSLATING**: Move to object position (interpolated over 25 steps)
3. **WAITING2**: Wait for distance sensor confirmation
4. **GRASPING**: Close gripper and lift object
5. **TRANSLATING_BACK**: Return to home position
6. **ROTATING**: Rotate to drop zone
7. **RELEASING**: Open gripper
8. **ROTATING_BACK**: Return to initial position

### Controllers

#### Camera Controller (`camera_controller.py`)
- Waits for `"STOP"` message from conveyor
- Captures camera image (1024x768 RGB)
- Sends image to YOLO server via TCP (127.0.0.1:5050)
- Receives object angle from YOLO
- Uses Webots Recognition API for object position
- Sends `[x, y, z, angle_rad]` to arm controller

#### Arm Controller (`arm_controller.py`)
- Receives position + angle from camera
- Executes state machine for pick-and-place
- Uses 2D planar inverse kinematics
- Controls UR10e motors and Robotiq 3-finger gripper
- Sends `"START_CONV"` to conveyor after object release

#### Conveyor Controller (`conveyor_controller.py`)
- Controls belt motor speed
- Monitors 3 distance sensors (ds1, ds2, ds3)
- Sends `"STOP"` to camera when object detected (ds1)
- Resumes belt after 2-second delay
- Receives `"START_CONV"` from arm to restart after pick

## Troubleshooting

### YOLO Server Connection Failed
- Make sure `yolo_server.py` is running **before** starting Webots
- Check that port 5050 is not blocked by firewall
- Verify `best.pt` model file exists in `yolo_server/`

### Camera Not Detecting Objects
- Ensure objects have `recognitionColors` defined in world file
- Check camera Recognition API is enabled
- Verify camera field of view covers the conveyor belt

### Arm Not Moving
- Check that position data is being received (see console output)
- Verify motor device names match world file
- Ensure distance sensor threshold (500) is appropriate

### Gripper Not Grasping
- Adjust gripper close position (default: 0.85)
- Check object size and gripper finger limits
- Verify distance sensor detects object proximity

## Key Parameters

| Parameter | Value | Location |
|:---|:---|:---|
| YOLO Server Port | 5050 | `camera_controller.py`, `yolo_server.py` |
| Belt Speed | 0.2 | `conveyor_controller.py` (arg 1) |
| Stop Duration | 2.0 seconds | `conveyor_controller.py` |
| Translation Steps | 25 | `arm_controller.py` |
| Distance Threshold | 500 | `arm_controller.py` |
| Gripper Close | 0.85 | `arm_controller.py` |

## Next Steps

- [ ] Test YOLO server independently
- [ ] Verify individual controllers
- [ ] Run full integration test
- [ ] Tune parameters for optimal performance
- [ ] Add multi-object handling
