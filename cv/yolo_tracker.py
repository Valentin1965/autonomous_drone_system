import cv2
import time
import requests
from ultralytics import YOLO

API_URL = "http://127.0.0.1:8080/api/move"   # твій web.server
STOP_URL = "http://127.0.0.1:8080/api/stop"

# Клас, за яким будемо їхати (наприклад, person)
TARGET_CLASS = "person"

# Нормалізована швидкість (0..1), далі web.server множить на MAX_SPEED
FORWARD_SPEED = 0.6
LATERAL_GAIN = 0.8
CENTER_TOLERANCE = 0.1   # 10% ширини кадру

def send_move(forward, lateral, yaw=0.0):
    try:
        requests.post(API_URL, json={
            "forward": forward,
            "lateral": lateral,
            "yaw": yaw
        }, timeout=0.1)
    except Exception:
        pass

def send_stop():
    try:
        requests.post(STOP_URL, timeout=0.1)
    except Exception:
        pass

def main():
    model = YOLO("yolov8n.pt")  # легка модель
    cap = cv2.VideoCapture(0)   # або rtsp/file

    if not cap.isOpened():
        print("Camera not opened")
        return

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            h, w, _ = frame.shape
            cx_frame = w / 2

            results = model(frame, verbose=False)
            best_target = None
            best_area = 0

            for r in results:
                boxes = r.boxes
                for b in boxes:
                    cls_id = int(b.cls[0])
                    cls_name = model.names[cls_id]
                    if cls_name != TARGET_CLASS:
                        continue

                    x1, y1, x2, y2 = b.xyxy[0].tolist()
                    area = (x2 - x1) * (y2 - y1)
                    if area > best_area:
                        best_area = area
                        best_target = (x1, y1, x2, y2)

            if best_target is None:
                # Немає цілі → зупинка
                send_stop()
                cv2.imshow("YOLO", frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
                continue

            x1, y1, x2, y2 = best_target
            cx = (x1 + x2) / 2

            # Відхилення від центру кадру (-1..1)
            offset = (cx - cx_frame) / cx_frame

            # Якщо ціль майже по центру → їдемо вперед
            if abs(offset) < CENTER_TOLERANCE:
                forward = FORWARD_SPEED
                lateral = 0.0
            else:
                forward = FORWARD_SPEED * 0.5
                lateral = -offset * LATERAL_GAIN  # знак: якщо ціль праворуч → їдемо вправо

            # Нормалізуємо до [-1, 1]
            forward = max(-1.0, min(1.0, forward))
            lateral = max(-1.0, min(1.0, lateral))

            send_move(forward, lateral, 0.0)

            # Візуалізація
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0,255,0), 2)
            cv2.line(frame, (int(cx_frame), 0), (int(cx_frame), h), (255,0,0), 1)
            cv2.circle(frame, (int(cx), int((y1+y2)/2)), 4, (0,0,255), -1)
            cv2.imshow("YOLO", frame)

            if cv2.waitKey(1) & 0xFF == 27:
                break

    finally:
        send_stop()
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
