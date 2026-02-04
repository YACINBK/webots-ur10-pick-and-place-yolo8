@echo off
echo Starting YOLO Detection Server...
echo.
echo Make sure you have installed: pip install ultralytics numpy
echo.
cd yolo_server
python yolo_server.py
pause
