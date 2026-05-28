# Autonomous Ground Rover System — Загальний огляд проєкту

> Актуально: травень 2026. Цільове розгортання — **Варіант 2** (RPi + Pixhawk + GCS + сервер аналізу).

---

## Призначення системи

Автономний наземний ровер для агро-моніторингу виноградників (та інших культур).

Система вирішує три завдання:

| Завдання | Опис |
|----------|------|
| **Автономний рух** | Ровер самостійно об'їжджає міжряддя по GPS-маршруту |
| **CV навігація ряду** | Технічний зір коригує рух усередині ряду в реальному часі |
| **Фітомоніторинг** | Дві бокові камери знімають рослини, знімки передаються на сервер для YOLO-аналізу |

---

## Структура системи

```
┌─────────────────────────────────────────────────────────┐
│  ДРОН (Ровер)                                           │
│  ┌────────────┐   USB serial (MAVLink 115200)           │
│  │  Pixhawk   │──────────────────────────────────────►  │
│  │  GPS / рух │                                         │
│  └────────────┘                                         │
│  ┌────────────┐   Wi-Fi 5 GHz → HTTP POST JPEG          │
│  │  RPi +     │──────────────────────────────────────►  │
│  │  Oak-D     │   (ліва + права камера → GCS API)       │
│  └────────────┘                                         │
└───────────────────┬─────────────────────────────────────┘
                    │  (два канали: MAVLink SiK + Wi-Fi 5G)
                    ▼
┌─────────────────────────────────────────────────────────┐
│  СТАНЦІЯ GCS  (ноутбук / польовий планшет)              │
│                                                         │
│  python main.py --full  →  http://GCS:8080              │
│                                                         │
│  • Leaflet-карта маршруту, трек, флот                   │
│  • HUD: ARM, GPS, швидкість, курс (2 Гц)                │
│  • Місія: GPS-waypoints → MissionRunner                 │
│  • CV ряд: YOLO seg + depth corridor (hybrid)           │
│  • Геозона, preflight-перевірки                         │
│  • Оприскувач (ON/OFF + лог)                            │
│  • Моніторинг: зйомка L/R → офлайн-черга               │
│                                                         │
│  Канал до сервера: 5G-модем → інтернет → HTTPS          │
└───────────────────┬─────────────────────────────────────┘
                    │ HTTPS (один бік: тільки вгору)
                    │  POST /api/v1/analyze  (JPEG + контекст)
                    │  POST /api/v1/events   (маршрут, spray…)
                    ▼
┌─────────────────────────────────────────────────────────┐
│  СЕРВЕР АНАЛІЗУ  (окремий блок, один на N станцій)      │
│                                                         │
│  python -m server.main --port 8090                      │
│                                                         │
│  • YOLOv8 — inference по знімках                        │
│  • SQLite  — повна база роботи флоту:                   │
│      fleet_events          — де, коли, що робили        │
│      monitoring_captures   — знімки, GPS, оператор      │
│      monitoring_detections — висновки YOLO              │
└─────────────────────────────────────────────────────────┘
```

---

## Канали зв'язку

| Пара | Канал | Тип трафіку |
|------|-------|-------------|
| Pixhawk ↔ GCS | **868 MHz SiK radio** | MAVLink: керування, GPS, failsafe |
| RPi камери → GCS | **Wi-Fi 5 GHz** (HTTP POST) | JPEG знімки моніторингу L/R |
| GCS → Сервер | **5G-модем → інтернет → HTTPS** | JPEG + контекст, події флоту |

Дані моніторингу йдуть **лише вгору**: дрон → станція → сервер.  
Сервер повертає лише JSON-відповідь із результатами (HTTP response).

---

## Режими розгортання

### Варіант 1: розробка без заліза (ПК + симулятор)

```
ПК
 ├── PixhawkGPSSimulator (UDP 14550) — імітує FC + GPS
 ├── Flask GCS (порт 8080) — повний веб-інтерфейс
 └── CV tracker — відеофайли з assets/videos/
```

Один процес: `python main.py --full`

### Варіант 2: польове розгортання (цільове)

```
Ровер
 ├── Pixhawk (ArduPilot Rover) — рух, GPS, failsafe
 └── RPi companion
      ├── Oak-D (RGB + stereo depth) — CV навігація
      └── Wi-Fi → JPEG → GCS API

Станція (ноутбук)
 └── Flask GCS — маршрут, моніторинг, флот

Сервер аналізу (хмара / сервер)
 └── YOLOv8 + SQLite
```

---

## Компоненти та пакети

| Пакет | Призначення |
|-------|-------------|
| `main.py` | Точка входу, аргументи CLI, запуск режимів |
| `mavlink/` | MAVLink-підключення, GroundController, commander, offboard |
| `simulator/` | PixhawkGPSSimulator (UDP, fleet_registry) |
| `cv/` | YOLOSegmentationTracker, DepthRowPlanner, HazardDetector |
| `web/` | Flask GCS: маршрут, fleet, CV API, sprayer, geofence, monitoring API |
| `monitoring/` | MonitoringService, SurveyRunner, cameras, remote_client, offline_queue, event_uplink |
| `server/` | Незалежний сервер аналізу: Flask API, YOLO engine, SQLite database |
| `config/` | YAML-конфіги: system, cv, monitoring, server, mission, geofence |
| `tests/` | 22 unit/integration тести (pytest) |

---

## Алгоритм роботи системи

### 1. Запуск та ініціалізація

1. `main.py` читає `config/system.yaml` (або `SYSTEM_CONFIG` з env).
2. Ініціалізується FleetManager — список ровер-об'єктів з конфігу `fleet:`.
3. Запускаються симулятори (dev) або встановлюються MAVLink-з'єднання (поле).
4. Flask GCS стартує на `0.0.0.0:8080`.
5. Запускається daemon-воркер офлайн-черги (`monitoring/offline_queue.py`).

### 2. Автономний маршрут (GPS)

```
Оператор
  → Вмикає «Редагувати» → клікає точки на Leaflet-карті
  → Натискає «Старт маршруту»

MissionRunner (web/mission_runner.py)
  → arm()
  → goto_latlon(wp[0])
  → _follow_path():
      while not stop:
        перевірити: emergency_stop? → abort
        перевірити: hazard_blocks_motion()? → wait
        перевірити: geofence.check_position()? → abort
        dist <= arrival_radius_m (1.0 м)?
          → якщо остання точка → _complete_at_last() → зупинка
          → інакше → next waypoint
  → фаза: idle → running → at_last | completed | aborted
```

Подія `mission_run` надсилається на сервер через `event_uplink`.

### 3. CV навігація ряду

```
YOLOSegmentationTracker (cv/tracker.py)
  джерело: oakd | video | webcam | synthetic

  _tracking_loop():
    для кожного кадру:
      depth_u8 = DepthRowPlanner.plan() → corridor offset
      hazard_result = HazardDetector.analyze() → COCO (людина, тварина…)
      yolo_results = model(frame) → traversable / obstacle masks

      якщо hazard_stop або yolo_stop або depth_stop:
        MotionBridge.stop()  (зупинка через MAVLink)
        nav_source = "hazard" | "obstacle"
      інакше:
        offset = depth_plan.offset  (hybrid: depth першочерговий)
               або center_offset(left_mask, right_mask)  (YOLO fallback)
        forward = forward_speed (0.70)
        lateral = offset * lateral_gain (0.95)
        MotionBridge.move(forward, lateral)
        if |offset| < sprayer_row_tolerance: sprayer ON
```

### 4. Моніторинг рослин

```
Обстеження (survey або manual sample):

MonitoringService.start_survey(vehicle, waypoints)
  → SurveyRunner.start(waypoints)
      → для кожної точки:
          goto(wp) → зачекати dwell_s (2.5 с)
          analyze_point(crop, vehicle_id, lat, lon)
            → CameraRig.capture() → left_jpeg, right_jpeg
            → remote_client.analyze_stereo_remote(…)
                → POST /api/v1/analyze на сервер
                    (або → offline_queue.enqueue_capture() якщо немає 5G)
          → findings.json (локальний кеш)
          → push до GCS UI

На сервері (server/app.py → /api/v1/analyze):
  → зберегти JPEG
  → yolo_engine.run(left_jpeg, right_jpeg, crop)
  → db.save_capture() + db.save_detections()
  → повернути JSON з detections
```

### 5. Офлайн-черга (при відсутності 5G)

```
remote_client / event_uplink намагається POST → сервер
  ├── успішно → відповідь → findings.json
  └── ConnectError / Timeout
        → offline_queue.enqueue_capture(…) або enqueue_event(…)
           → зберегти на диск: data/monitoring/outbox/<ts>_<id>_*.json/.jpg

Daemon-воркер (кожні retry_interval_s = 30 с):
  GET /health → 200?
    ├── ні → чекати далі
    └── так → flush():
              для кожного item у черзі:
                POST → сервер → успішно → видалити файли
```

### 6. Аварійна зупинка

- `POST /api/emergency/stop` → `fleet.emergency_stop = True`
- MissionRunner і MotionBridge перевіряють флаг на кожній ітерації
- `ctrl.stop()` → MAVLink STOP команда до Pixhawk
- Апаратний E-stop рве живлення моторів

### 7. Геозона

- Оператор малює прямокутник на карті → `POST /api/geofence/set`
- При кожному кроці місії: `geofence.check_position(lat, lon)` → вихід за межі → abort
- При CV: `MotionBridge.move()` перевіряє геозону перед кожним velocity-командою

---

## Стан системи (GCS HUD — /api/status)

```json
{
  "connected": true,
  "armed": true,
  "gps": { "lat": 50.450, "lon": 30.523, "fix": 3 },
  "speed": 1.0,
  "heading": 45,
  "mission": { "active": true, "phase": "running", "index": 2 },
  "cv": { "running": true, "planner": "hybrid", "nav_source": "depth" },
  "sprayer": { "active": false },
  "geofence": { "enabled": true },
  "monitoring": { "active": false }
}
```

---

## База даних сервера аналізу (SQLite)

| Таблиця | Зберігає |
|---------|----------|
| `fleet_events` | де, коли, що робили; маршрут, spray, обстеження, оператор, payload |
| `monitoring_captures` | GPS, культура, шляхи до JPEG, контекст дрона, станція |
| `monitoring_detections` | висновки YOLO по кожному знімку (label, confidence, severity) |

Типи подій у `fleet_events`: `mission_run`, `sprayer_on`, `sprayer_off`, `monitoring_survey_start`, `monitoring_survey_end`, `monitoring_capture`.

---

## Конфігурація

| Файл | Призначення |
|------|-------------|
| `config/system.yaml` | Dev: MAVLink UDP, fleet, геозона, місія, web |
| `config/system_gcs.yaml` | Поле GCS: UDP radio IP, arrival_radius 2.5 м |
| `config/system_rpi.yaml` | Поле RPi: serial /dev/ttyACM0:115200 |
| `config/cv.yaml` | CV: planner, source, YOLO model, hazard |
| `config/cv_rpi.yaml` | CV на борту: source oakd, planner hybrid |
| `config/monitoring.yaml` | Станція: uplink (local/rpi), remote, offline_queue, cameras, crops |
| `config/server.yaml` | Сервер аналізу: db, models, api_key, device |
| `config/mission.yaml` | GPS-waypoints для місії |

---

## Тести

```bash
bash scripts/run_tests.sh        # 22 тести, без YOLO/torch (~30 с)
pytest tests/ -q                 # повний набір (потрібен requirements-dev.txt)
```

Тести охоплюють: симулятор, Flask API, місія (runner, last-stop), fleet, preflight, geofence, CV motion, hazard detector, monitoring server DB, offline queue, remote client.

---

## Посилання на документацію

| Документ | Зміст |
|----------|-------|
| [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) | Архітектурні рішення Sprint 1 |
| [`docs/VARIANT_2_SETUP.md`](VARIANT_2_SETUP.md) | Польове розгортання RPi+Pixhawk+GCS |
| [`docs/FIELD_DAY.md`](FIELD_DAY.md) | Чекліст польового дня |
| [`docs/MONITORING_REMOTE.md`](MONITORING_REMOTE.md) | Моніторинг: архітектура, API, offline-черга |
| [`docs/SIM_DEV.md`](SIM_DEV.md) | Розробка без заліза (симулятор) |
| [`docs/SIM_STABILITY_CHECKLIST.md`](SIM_STABILITY_CHECKLIST.md) | Чекліст стабільності dev/sim (перед полем) |
| [`docs/RUN_COMMANDS.md`](RUN_COMMANDS.md) | Команди запуску всіх компонентів |
| [`Algorithm_autonomous_drone_system.md`](../Algorithm_autonomous_drone_system.md) | PX4 / QGC операційні нотатки |
