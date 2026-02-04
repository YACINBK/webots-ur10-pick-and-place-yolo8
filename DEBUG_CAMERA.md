# Debugging Camera-on-Arm Setup

## Check Camera Output in Webots

1. **Open Camera Window in Webots:**
   - Tools → Overlays → Camera Devices
   - You should see "camera_robot: camera" in the list
   - Click it to open the camera view window

2. **What to Look For:**
   - When arm is in SCANNING pose, camera should show conveyor belt from above
   - If you see only gripper/arm parts, camera isn't positioned correctly
   - If window is black, camera robot has issues

## Verify Scanning Pose Geometry

Current setup:
- **Arm base**: (0.85, -1.07, 0.64)  
- **Conveyor**: (-0.4, -0.14, 0) - about 1.25m away in X, 0.93m in Y
- **Current SCAN_SHOULDER_PAN**: -0.8 radians (~-46°)

**Issue**: The arm rotates around its base Z-axis. With the arm rotated 90° (`rotation 0 0 1 1.5702`), panning left (-0.8) might not reach the conveyor.

## Quick Test

Add this debug print to see where end-effector actually is:

In `arm_controller.py`, after moving to scanning pose (around line 189), add:
```python
print(f"[DEBUG] Scanning pose end-effector position: pan={self.SCAN_SHOULDER_PAN}")
```

## Expected Behavior

When you reload and run:
1. Arm should move (you'll see it swing)  
2. Console should show: `[Bras] Moving to scanning pose for detection`
3. Console should show: `[Bras] In scanning pose, waiting for detection`
4. Camera window should show conveyor with piece visible

## If Camera Still Can't See Conveyor

The scanning pose angles might need adjustment. We may need to calculate proper pose based on:
- Arm's 90° base rotation
- Actual conveyor position relative to arm
- Camera's 0.5m height offset on toolSlot
