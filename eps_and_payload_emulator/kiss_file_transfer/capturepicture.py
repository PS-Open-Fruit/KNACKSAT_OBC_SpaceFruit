import cv2
import datetime
import os


cap = cv2.VideoCapture(0)
ret, frame = cap.read()

if ret:
    filename = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"
    cv2.imwrite(filename, frame)
    print(f"Captured: {filename}")
else:
    print("Error: Failed to capture image from camera.")

cap.release()