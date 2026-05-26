# Autonomous Ground Rover System

Наземний автономний робот (rover): MAVLink, симулятор GPS/FC, веб-панель, комп’ютерний зір (виноградник / ряди).

**Архітектура:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)  
**Операційні нотатки (PX4, QGC):** [`Algorithm_autonomous_drone_system.md`](Algorithm_autonomous_drone_system.md)

## Primary stack (Sprint 1)

| Component | Path |
|-----------|------|
| Entry point | `main.py` |
| MAVLink | `mavlink/` |
| CV (YOLO + OAK-D) | `cv/` |
| Web API / UI | `web/` |
| FC + GPS simulator | `simulator/pixhawk_simulator.py` |
| Config | `config/` |

> **Не використовуйте** пакет `vision/` — застарілий stub; див. `vision/README.md`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# optional dev tools
pip install -r requirements-dev.txt
```

Place YOLO weights in `models/` (e.g. `yolov8s-seg.pt`) or project root; `*.pt` is gitignored.

## Run (development)

**Обидва термінали** — з каталогу проєкту та з venv:

```bash
cd ~/autonomous_drone_system
source .venv/bin/activate
```

**Один термінал (рекомендовано для dev):**

```bash
python main.py --full
# у другому вікні термінала або тому ж після Ctrl+C:
curl -X POST http://127.0.0.1:8080/api/arm
curl -X POST http://127.0.0.1:8080/api/move -H "Content-Type: application/json" \
     -d '{"forward":0.5,"lateral":0,"yaw":0}'
```

**Два термінали:**

```bash
# Terminal 1
python main.py --simulator

# Terminal 2
python main.py --web
```

**PX4 / SITL** (замість симулятора):

```bash
export MAVLINK_PROFILE=px4   # опційно
python main.py --px4
python main.py --px4 --mission
```

Конфіг: `config/system.yaml` → `mavlink.connection_sim` / `connection_px4`, `simulator.connection_string`.

**CV:** `cv/tracker.py` + `MotionBridge`. Зараз — **відеофайли**, пізніше — камери.

1. Покладіть відео в [`assets/videos/`](assets/videos/README.md) (наприклад `vineyard_demo.mp4`)
2. У `config/cv.yaml`: `source: video` (вже так)
3. Запуск:

```bash
python main.py --full
# браузер → ▶ YOLO трекер

# або окремо CV (потрібен --full / --web + симулятор):
python main.py --cv-video
```

Після збірки апаратної частини в `config/cv.yaml`:

```yaml
source: oakd    # або webcam
```

## Tests (Sprint 1 / Day 5)

```bash
pip install -r requirements-ci-light.txt
bash scripts/run_tests.sh
# або:
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
pytest tests/test_simulator.py tests/test_flask_api.py tests/test_runtime_config.py -q
```

Повний набір (+ YOLO, повільно): `pip install -r requirements-dev.txt && pytest tests/ -q`

Швидкий старт: [`docs/QUICKSTART.md`](docs/QUICKSTART.md)

## ROS 2 workspace (optional, Phase 2)

```bash
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash
ros2 launch drone_sitl sitl_full.launch.py
```

Packages: `drone_mission`, `drone_rtk`, `drone_diagnostics`, `drone_visualizer`, `drone_sitl`, `drone_rviz`.

## Станція керування (Web GCS)

Після `python main.py --full` відкрийте http://127.0.0.1:8080/

- Карта **OpenStreetMap** + трек руху
- **HUD** — ARM, GPS, швидкість, курс (опит 2 Гц)
- D-pad рух (утримання кнопки), ARM/DISARM, CV, оприскувач

## Config

- `config/system.yaml` — MAVLink `udp:127.0.0.1:14550`, web `:8080`
- `config/mission.yaml` — local waypoints
