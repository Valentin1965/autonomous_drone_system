# Algorithm of actions: ARM, takeoff, missions, offboard, computer vision

┌──────────────────────────────────────────────────────────────────────┐
│                        AUTONOMOUS DRONE SYSTEM                        │
└──────────────────────────────────────────────────────────────────────┘

                         (1) PX4 SITL / Pixhawk
                         ───────────────────────
┌──────────────────────────────────────────────────────────────────────┐
│  PX4 Autopilot (SITL / Hardware)                                     │
│                                                                      │
│  • EKF2 (позиція, орієнтація)                                        │
│  • MPC (контролер швидкості)                                         │
│  • Mission mode / Offboard mode                                      │
│  • MAVLink router (UDP 14550)                                        │
│                                                                      │
│  Вихід: MAVLink HEARTBEAT, GPS, ATTITUDE, LOCAL_NED, SYS_STATUS      │
│  Вхід: SET_POSITION_TARGET_LOCAL_NED / GLOBAL_INT                    │
└──────────────────────────────────────────────────────────────────────┘
                         │
                         │ UDP 14550 (MAVLink)
                         ▼

┌──────────────────────────────────────────────────────────────────────┐
│                         (2) Python Backend                           │
│                         web.server (Flask)                           │
│                                                                      │
│  Модулі:                                                             │
│   • mavlink/connection.py — підключення до PX4                       │
│   • mavlink/commander.py — arm, disarm, takeoff, land                │
│   • mavlink/offboard.py — offboard‑маневри                          │
│   • missions/ — завантаження та виконання місій                      │
│                                                                      │
│  API:                                                                │
│   • /api/arm, /api/disarm                                            │
│   • /api/takeoff, /api/land                                          │
│   • /api/move (velocity control)                                     │
│   • /api/stop                                                        │
│   • /api/status                                                      │
│   • /api/set_mode (earth/body)                                       │
│                                                                      │
│  CV‑модуль (YOLOv8):                                                 │
│   • /api/cv/start, /api/cv/stop                                      │
│   • /api/cv/target (вибір класу)                                     │
│                                                                      │
│  Потоки:                                                             │
│   • Main Flask thread                                                │
│   • CV thread (YOLOv8)                                               │
│                                                                      │
│  Логіка CV:                                                          │
│   • Follow Object                                                    │
│   • Auto‑stop (за площею боксу)                                      │
│   • Obstacle Avoidance (клас “car”)                                  │
└──────────────────────────────────────────────────────────────────────┘
                         │
                         │ HTTP (localhost:8080)
                         ▼

┌──────────────────────────────────────────────────────────────────────┐
│                         (3) Web UI (Frontend)                        │
│                                                                      │
│  Компоненти:                                                         │
│   • HUD (телеметрія)                                                 │
│   • Карта (Leaflet + OSM)                                            │
│   • Джойстик (pointer events)                                        │
│   • Кнопки руху                                                      │
│   • Перемикач Earth/Body                                             │
│   • CV MODE ON/OFF                                                   │
│   • Вибір класу YOLO (person/car/dog/banana)                         │
│                                                                      │
│  JS‑логіка:                                                          │
│   • pollTelemetry() — 2 Гц                                           │
│   • startMove() / stopMove()                                         │
│   • toggleCV()                                                       │
│   • setCVTarget()                                                    │
└──────────────────────────────────────────────────────────────────────┘
                         │
                         │ User Interaction
                         ▼

┌──────────────────────────────────────────────────────────────────────┐
│                         (4) Operator / User                          │
│                                                                      │
│  • Керує дроном через UI                                             │
│  • Вмикає CV‑режим                                                   │
│  • Обирає ціль YOLO                                                  │
│  • Спостерігає за картою та HUD                                      │
└──────────────────────────────────────────────────────────────────────┘
---

## 0. Initial conditions (every session)

1. **Start PX4 SITL (GZ) in WSL2**
   - In WSL2:
     ```bash
     cd ~/PX4-Autopilot
     make px4_sitl_default gz_x500
     ```

2. **Start MAVLink stream to Windows (QGC)**
   - In PX4 console (`pxh>`):
     ```bash
     mavlink stop-all
     mavlink start -u 14556 -o 14550 -t 172.19.176.1 -m onboard -r 20000
     ```
   - After that PX4 should print:
     ```text
     INFO [commander] Ready for takeoff!
     ```

3. **Start QGroundControl in Windows**
   - Comm Link:
     - **Type:** UDP  
     - **Port:** `14550`  
     - **Server Address:** `127.0.0.1:14550`  
   - Link status: `PX4 (Connected)`  
   - Top bar: `NOT READY / READY / LAND / PX4#`

---

## 1. ARM from QGroundControl

1. **Check that QGC sees the vehicle**
   - In the top bar you see:
     - `PX4#`
     - flight mode (e.g. `LAND`)
     - satellites, etc.

2. **Ensure PX4 is READY**
   - If needed (once, already done):
     ```bash
     param set COM_ARM_WO_GPS 1
     param set COM_PREARM_MODE 0
     param save
     ```
   - In normal case you already see:
     ```text
     INFO [commander] Ready for takeoff!
     ```

3. **ARM in QGC**
   - Go to **Fly** view.
   - Press **ARM** (lock icon / ARM button).
   - Status changes to `ARMED`, mode stays `LAND` or `POSCTL`.

---

## 2. Takeoff from QGroundControl

### Variant A — Takeoff button

1. **ARM** (as in section 1).
2. In **Fly** view press **Takeoff**.
3. Set target altitude (e.g. `3–5 m`).
4. Confirm.
5. Status sequence:
   - `TAKEOFF` → `HOLD` / `POSCTL` / `AUTO` (depends on configuration).

### Variant B — via flight mode

1. **ARM**.
2. Select mode **Takeoff** (if available in your build).
3. PX4 performs automatic takeoff to default altitude.

---

## 3. Missions from QGroundControl

1. **Create mission**
   - Go to **Plan** tab.
   - On the map add:
     - **Takeoff** point.
     - Several **Waypoint** points.
     - **Land** point (optional).
   - Check altitude and order of waypoints.

2. **Upload mission to PX4**
   - Press **Upload** (send mission to vehicle).
   - Wait for confirmation.

3. **Run mission**
   - Go to **Fly** tab.
   - **ARM** the vehicle.
   - Select mode **Mission / AUTO**.
   - Press **Start Mission**.
   - PX4 will:
     - take off,
     - fly through waypoints,
     - land (if Land item exists).

---

## 4. Offboard control from Python

### 4.1. General sequence

1. **Start PX4 SITL + MAVLink + QGC** (section 0).
2. **Start Python project**
   - In WSL2:
     ```bash
     cd ~/autonomous_drone_system
     python3 main.py
     ```

3. **In Python (high-level logic)**

   1. **Connect to PX4 via MAVLink**
      - e.g. `udp:127.0.0.1:14550` (inside WSL2).
   2. **Wait for heartbeat**.
   3. **Set mode OFFBOARD**:
      - via `SET_MODE` or `MAV_CMD_DO_SET_MODE`.
   4. **ARM**:
      - via `MAV_CMD_COMPONENT_ARM_DISARM`.
   5. **Start sending setpoints at ≥ 2 Hz**:
      - position setpoints:
        - `SET_POSITION_TARGET_LOCAL_NED`
      - or velocity setpoints:
        - same message with velocity mask.
   6. **Maintain continuous stream of setpoints**:
      - if stream stops → PX4 exits OFFBOARD for safety.
   7. **Finish mission**:
      - send `MAV_CMD_NAV_LAND`
      - or switch mode to `LAND` / `POSCTL`.

### 4.2. Typical offboard scenario

1. Takeoff to 3–5 m (either via QGC or via Python).
2. Fly a pattern:
   - square, circle, line, etc.
3. Return to initial point.
4. Land (command or mode change).

---

## 5. Computer vision (CV) + offboard

### 5.1. System architecture

1. **Video source**
   - real camera
   - or simulated camera / video stream.

2. **CV module (Python)**
   - OpenCV + detector (e.g. YOLOv8).
   - Input: frame.
   - Output: detected objects / target coordinates.

3. **Decision logic**
   - Example:
     - “If target detected → fly towards it.”
     - “If obstacle detected → change trajectory.”

4. **Offboard controller**
   - Receives target position / velocity from CV logic.
   - Converts it into MAVLink setpoints (as in section 4).
   - Sends them to PX4 at stable frequency.

5. **Control loop**
   - Capture frame → CV → decision → new setpoint → PX4 → drone motion.
   - Repeat at fixed rate (e.g. 10–30 Hz for CV, 10–20 Hz for setpoints).

---

## 6. Minimal daily workflow

1. **Start PX4 SITL (WSL2).**
2. **Start MAVLink to Windows (mavlink start -u 14556 -o 14550 -t 172.19.176.1 ...).**
3. **Start QGC (Windows), check PX4 in top bar.**
4. **ARM + Takeoff from QGC** *or* from Python.
5. **Run mission**:
   - via QGC (Plan → Mission),
   - or via Python offboard.
6. **Optionally run CV module**:
   - CV → decision → offboard setpoints.
7. **Land and disarm.**



Набір команд у pxh> після запуску SITL
make px4_sitl_default gazebo
# у pxh>:
mavlink stop-all
mavlink start -x -u 14550 -r 200000 -m onboard
param save

# 1. Увімкнути MAVLink на UDP, де слухає твій web.server (14550)
mavlink stop-all
mavlink start -x -u 14550 -r 200000 -m onboard
mavlink start -x -u 14540 -r 200000 -m external   # якщо хочеш ще QGC

# 2. Переконатися, що EKF має GPS (для earth-frame)
param set EKF2_AID_MASK 24        # GPS + vision (або 3 для тільки GPS)
param set EKF2_HGT_MODE 0         # висота по баро

# 3. Для наземного дрона (якщо ти моделюєш ground vehicle)
param set MIS_TAKEOFF_ALT 3
param set MPC_XY_VEL_MAX 2.0
param set MPC_XY_CRUISE 1.0

# 4. Зберегти параметри
param save


cd ~/autonomous_drone_system
python3 -m web.server

cd ~/autonomous_drone_system
python3 -m cv.yolo_tracker

http://localhost:8080


Запуск комп’ютерного бачення (YOLOv8)
curl -X POST http://127.0.0.1:8080/api/cv/start
curl -X POST http://127.0.0.1:8080/api/cv/stop
curl http://127.0.0.1:8080/api/cv/status
curl -X POST http://127.0.0.1:8080/api/cv/target \
     -H "Content-Type: application/json" \
     -d '{"target":"person"}'

API для керування дроном
ARM
curl -X POST http://127.0.0.1:8080/api/arm

DISARM
curl -X POST http://127.0.0.1:8080/api/disarm

Takeoff
curl -X POST http://127.0.0.1:8080/api/takeoff -d '{"alt":3}'

Land
curl -X POST http://127.0.0.1:8080/api/land

Рух (velocity control)
curl -X POST http://127.0.0.1:8080/api/move \
     -H "Content-Type: application/json" \
     -d '{"forward":0.5, "lateral":0.0, "yaw":0.0}'

STOP
curl -X POST http://127.0.0.1:8080/api/stop

Перемикання Earth/Body
curl -X POST http://127.0.0.1:8080/api/set_mode \
     -H "Content-Type: application/json" \
     -d '{"mode":"earth"}'
або

-d '{"mode":"body"}'

Як використовувати:
Bash# 1. Запуск симулятора
python main.py --simulator

# 2. Запуск з PX4 / SITL
python main.py --px4

# 3. Запуск тільки CV режиму (YOLO + Oak-D)
python main.py --cv

# 4. Повний режим (Flask + CV + можливість керування)
python main.py --all

