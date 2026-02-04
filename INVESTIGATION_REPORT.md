# Investigation Report: YOLO Detection and Camera Issues

## Problem Statement
The arm hangs when detecting a piece, indicating issues with YOLO and detection logic.

## Code Analysis

### Issue #1: Camera Recognition Buffer Not Ready
**Location**: `camera_controller.py`, lines 106-112

**Problem**: The camera tries to read recognition objects immediately after receiving STOP signal, but the recognition buffer may not be populated yet.

**Current Code**:
```python
for _ in range(5):
    num_objects = self.camera.getRecognitionNumberOfObjects()
    if num_objects > 0:
        break
    self.robot.step(self.timestep)
```

**Analysis**: 
- Only waits for max 5 steps (160ms at 32ms timestep)
- May not be enough time for recognition to stabilize
- If objects not detected, continues anyway which causes issues

### Issue #2: No Retry or Error Handling for Failed Detections
**Location**: `camera_controller.py`, lines 117-136

**Problem**: When `num_objects == 0`, the code prints a warning but doesn't send any data to the arm. The arm continues waiting indefinitely in `State.WAITING`.

**Current Code**:
```python
if num_objects > 0:
    # ... send data to arm
else:
    print("Warning: No objects detected by camera recognition")
    # NO DATA SENT TO ARM - ARM HANGS HERE
```

**Impact**: 
- Arm stays in `WAITING` state forever
- System becomes unresponsive
- This is the root cause of the "hanging" behavior

### Issue #3: YOLO Server Connection Not Resilient
**Location**: `camera_controller.py`, lines 41-49

**Problem**: If YOLO server connection fails or disconnects, there's no reconnection logic.

**Current Code**:
```python
def connect_to_yolo_server(self):
    try:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect(('127.0.0.1', 5050))
        print("Connected to YOLO server")
    except Exception as e:
        print(f"Error connecting to YOLO server: {e}")
        # sock remains None - all future calls will fail
```

**Impact**: 
- If initial connection fails, all subsequent YOLO calls fail
- No retry mechanism
- Silent failures in `send_image_to_yolo()`

### Issue #4: Race Condition in Arm State Machine
**Location**: `arm_controller.py`, lines 152-166

**Problem**: The arm only accepts detection data when in `WAITING` state, but processes all messages in the queue at once.

**Current Code**:
```python
if self.cam_receiver.getQueueLength() > 0:
    if self.state == State.WAITING:
        data_str = self.cam_receiver.getString()
        # ... process data
    
    # Always clear the queue
    while self.cam_receiver.getQueueLength() > 0:
        self.cam_receiver.nextPacket()
```

**Analysis**: 
- Good: Prevents processing stale data
- Bad: If multiple STOP signals sent, only first is processed
- Could miss valid detections if timing is off

### Issue #5: YOLO Angle Handling Incomplete
**Location**: `camera_controller.py`, lines 122-126

**Problem**: When YOLO fails (returns -999), angle is set to 0, which may not be appropriate for all objects.

**Current Code**:
```python
angle_rad = 0.0
if angle_deg != -999.0:
    angle_rad = angle_deg * math.pi / 180.0
```

**Impact**: 
- Objects may be grasped at wrong angle
- Gripper may not close properly
- Pick operation may fail

### Issue #6: No Timeout in Arm WAITING2 State
**Location**: `arm_controller.py`, lines 215-221

**Problem**: Arm waits indefinitely for `GO_DOWN` signal from conveyor.

**Current Code**:
```python
elif self.state == State.WAITING2:
    self.wrist3.setPosition(self.object_angle)
    if self.go_down_received:
        print("[Bras] Buffered GO_DOWN detected, starting descent.")
        self.go_down_received = False
        self.state = State.DESCENDING
    # NO TIMEOUT - waits forever
```

**Impact**: 
- If GO_DOWN signal is lost or never sent, arm hangs
- No recovery mechanism

## Root Cause Analysis

The primary issue causing the arm to hang is **Issue #2**: When the camera recognition API fails to detect objects (returns 0), no position data is sent to the arm, causing it to wait indefinitely in the `WAITING` state.

This can happen when:
1. Recognition buffer is not ready (Issue #1)
2. Object doesn't have proper `recognitionColors` in world file
3. Object is outside camera field of view
4. Camera is not positioned correctly

## Recommended Fixes

### Critical Fixes (Must Implement)

1. **Add Fallback Detection Logic in Camera Controller**
   - Increase wait time for recognition buffer
   - Add retry mechanism if detection fails
   - Send abort signal to arm if detection repeatedly fails

2. **Add Timeout and Recovery in Arm Controller**
   - Add timeout in `WAITING` state (e.g., 10 seconds)
   - Add timeout in `WAITING2` state for GO_DOWN signal
   - Reset to initial state on timeout

3. **Improve Error Messages and Logging**
   - Add detailed logging for each detection attempt
   - Log camera position, recognition status, YOLO status
   - Add debug mode to save camera images

### Secondary Fixes (Should Implement)

4. **Add YOLO Reconnection Logic**
   - Retry connection on failure
   - Reconnect if socket error occurs

5. **Improve Angle Handling**
   - Use object geometry for fallback angle
   - Add confidence threshold for YOLO angles

6. **Add Health Monitoring**
   - Periodic status messages from all controllers
   - Watchdog timer for system health

## Testing Recommendations

1. Test with YOLO server offline
2. Test with objects outside camera FOV
3. Test with objects without recognitionColors
4. Test timing under various conditions
5. Add debug logging to track state transitions

## Next Steps

1. Implement critical fixes first (detection fallback and timeouts)
2. Test each fix independently
3. Run full integration test
4. Document changes and update README
