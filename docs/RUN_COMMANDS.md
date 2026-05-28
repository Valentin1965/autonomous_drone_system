# Команди запуску — Autonomous Ground Rover System

> Усі команди виконуються з кореневої папки проєкту: `~/autonomous_drone_system`

---

## Підготовка середовища (один раз)

```bash
cd ~/autonomous_drone_system

# Створити venv
python3 -m venv .venv
source .venv/bin/activate

# Встановити залежності
pip install -r requirements.txt

# Опційно: dev-інструменти (pytest, flake8, mypy)
pip install -r requirements-dev.txt

# Розмістити YOLO-моделі у папці models/
# (напр.: yolov8s-seg.pt, yolov8s.pt)
ls models/
```

---

## 1. Розробка без заліза (симулятор)

### Рекомендований режим — один термінал

```bash
python main.py --full
# → http://127.0.0.1:8080/
```

Або через скрипт:

```bash
bash scripts/run_sim_dev.sh
```

### Два термінали (для відлагодження)

```bash
# Термінал 1 — симулятор MAVLink (foreground)
python main.py --simulator

# Термінал 2 — Flask GCS
python main.py --web
```

### З підказкою CV

```bash
python main.py --all
# те саме, що --full + підказка про CV hybrid assets/videos/
```

### Явний конфіг

```bash
python main.py --full --config config/system.yaml
```

---

## 2. Computer Vision (CV навігація ряду)

> Потребує запущеного GCS (`--full` або `--web` + симулятор).

### CV з відеофайлу (dev)

Покладіть `.mp4` у `assets/videos/`, потім:

```bash
python main.py --full
# У GCS браузері: кнопка «▶ YOLO трекер» → CV стартує
```

Або окремо (після старту --full в іншому терміналі):

```bash
python main.py --cv-video
```

### CV з вебкамери

```bash
python main.py --cv-webcam
```

### CV на RPi з Oak-D (поле)

```bash
# Встановити в config/cv_rpi.yaml:
#   source: oakd
#   planner: hybrid

python main.py --cv
# або через скрипт (автоматично встановлює CV_CONFIG):
bash scripts/run_variant2_rpi.sh
```

### Змінні середовища для CV

```bash
export CV_CONFIG=config/cv_rpi.yaml   # шлях до конфігу CV
export CV_SOURCE=oakd                  # oakd | video | webcam | synthetic
```

---

## 3. Польове розгортання — Варіант 2 (RPi + Pixhawk + GCS)

### Перевірка борту перед виїздом (RPi)

```bash
bash scripts/preflight_variant2.sh
```

Перевіряє: Python, пакети, конфіги, serial `/dev/ttyACM0`, depthai, YOLO-моделі.

### RPi (борт — CV + MAVLink до Pixhawk)

```bash
# Переконайтесь, що serial доступний:
sudo usermod -aG dialout $USER   # один раз, потім перелогінитись
ls -l /dev/ttyACM0

# Запуск
bash scripts/run_variant2_rpi.sh
```

Що встановлює скрипт автоматично:

```bash
export SYSTEM_CONFIG=config/system_rpi.yaml   # serial /dev/ttyACM0:115200
export CV_CONFIG=config/cv_rpi.yaml           # source: oakd, planner: hybrid
export MAVLINK_PROFILE=px4
```

Або вручну:

```bash
export SYSTEM_CONFIG=config/system_rpi.yaml
export CV_CONFIG=config/cv_rpi.yaml
export MAVLINK_PROFILE=px4
python main.py --cv
```

### GCS (станція — маршрут, моніторинг, флот)

```bash
# Спочатку: виправте IP радіо в config/system_gcs.yaml:
#   mavlink.connection_px4: "udp:192.168.1.10:14550"

bash scripts/run_variant2_gcs.sh

# HTTPS (self-signed dev):
bash scripts/gen_dev_tls_cert.sh
# У config/system_gcs.yaml: web.tls.enabled: true
# Браузер: https://127.0.0.1:8080/

# Захист API GCS:
export GCS_API_KEY=your_secret   # або web.security.api_key у YAML
# У GCS UI: поле 🔑 у верхній панелі (sessionStorage)
# → http://127.0.0.1:8080/
```

Або вручну:

```bash
export SYSTEM_CONFIG=config/system_gcs.yaml
export MAVLINK_PROFILE=px4
python main.py --web
```

### Явний конфіг без скриптів

```bash
# GCS
python main.py --web --config config/system_gcs.yaml

# RPi
python main.py --cv --config config/system_rpi.yaml
```

### Автозапуск RPi (systemd)

```ini
# /etc/systemd/system/rover-cv.service
[Unit]
Description=Rover CV variant 2
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/autonomous_drone_system
Environment=SYSTEM_CONFIG=config/system_rpi.yaml
Environment=CV_CONFIG=config/cv_rpi.yaml
Environment=MAVLINK_PROFILE=px4
ExecStart=/home/pi/autonomous_drone_system/.venv/bin/python main.py --cv
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable rover-cv
sudo systemctl start rover-cv
sudo systemctl status rover-cv
```

---

## 4. PX4 / SITL (реальний автопілот або PX4 SITL)

```bash
# Підключитись до автопілота (чекати ARM/move вручну або через API)
export MAVLINK_PROFILE=px4
python main.py --px4

# Підключитись + виконати config/mission.yaml
python main.py --px4 --mission
```

---

## 5. Сервер аналізу (окремий блок)

> Сервер запускається незалежно від GCS. Один сервер — багато станцій.

### Dev / без YOLO (лише БД)

```bash
python -m server.main --port 8090
# або:
python scripts/start_analysis_server.py --port 8090
```

### З реальними YOLO-вагами

```bash
python scripts/start_analysis_server.py \
  --port 8090 \
  --vineyard-weights models/vineyard.pt \
  --device cpu \
  --confidence 0.45
```

### Параметри сервера

```bash
python -m server.main \
  --host 0.0.0.0 \
  --port 8090 \
  --device cuda          # cpu | cuda | mps
  --confidence 0.45 \
  --api-key SECRET \     # Bearer-токен (опційно)
  --db data/fleet.db \   # шлях до SQLite (перебиває config/server.yaml)
  --vineyard-weights /path/to/vineyard.pt \
  --banana-weights /path/to/banana.pt \
  --default-weights /path/to/default.pt
```

### Змінні середовища для сервера

```bash
export MONITORING_API_KEY=your_secret
export YOLO_DEVICE=cuda
export YOLO_CONF=0.45
export MONITORING_VINEYARD_WEIGHTS=/path/to/vineyard.pt
export MONITORING_BANANA_WEIGHTS=/path/to/banana.pt
export MONITORING_DEFAULT_WEIGHTS=/path/to/default.pt
```

Конфіг: `config/server.yaml`

### Перевірка роботи сервера

```bash
# Health
curl http://127.0.0.1:8090/health

# Дашборд (HTML)
# http://127.0.0.1:8090/dashboard

# Статистика БД
curl http://127.0.0.1:8090/api/v1/stats

# Список знахідок
curl "http://127.0.0.1:8090/api/v1/findings?limit=10"

# Журнал подій флоту
curl "http://127.0.0.1:8090/api/v1/operations?limit=10"
```

---

## 6. Налаштування моніторингу на станції

Відредагуйте `config/monitoring.yaml` перед польовим виїздом:

```yaml
station:
  id: gcs-1
  operator: "Ім'я оператора"

remote:
  mode: remote          # замість mock
  base_url: "http://SERVER_IP:8090"
  api_key: "SECRET"     # якщо сервер запущено з --api-key

uplink:
  source: rpi           # rpi = камери на борту RPi; local = камери на GCS
  rpi:
    host: "192.168.1.20"
    port: 8081
```

### API офлайн-черги (GCS)

```bash
# Preflight (будь-який дрон флоту)
curl "http://127.0.0.1:8080/api/preflight?vehicle_id=rover_2&require_route=1"

# Статус черги
curl http://127.0.0.1:8080/api/monitoring/queue

# Примусово відправити чергу на сервер
curl -X POST http://127.0.0.1:8080/api/monitoring/queue/flush
```

---

## 7. Тести

```bash
# Легкі тести (без YOLO/torch, ~30 с)
bash scripts/run_tests.sh

# Те саме вручну
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export DRONE_SIM_INTERACTIVE=0
python -m pytest tests/ -q -m "not slow"

# Повний набір (потрібен requirements-dev.txt з ultralytics)
pip install -r requirements-dev.txt
pytest tests/ -q

# Окремі тести
pytest tests/test_flask_api.py tests/test_simulator.py -q
pytest tests/test_monitoring_server_db.py -q
pytest tests/test_mission_runner.py -q
```

---

## 8. Корисні API запити (curl)

```bash
# ARM
curl -X POST http://127.0.0.1:8080/api/arm

# Ручний рух
curl -X POST http://127.0.0.1:8080/api/move \
     -H "Content-Type: application/json" \
     -d '{"forward":0.5,"lateral":0,"yaw":0}'

# Стоп
curl -X POST http://127.0.0.1:8080/api/stop

# Аварійна зупинка
curl -X POST http://127.0.0.1:8080/api/emergency/stop

# Статус (телеметрія)
curl http://127.0.0.1:8080/api/status

# Флот
curl http://127.0.0.1:8080/api/fleet

# Оприскувач
curl -X POST http://127.0.0.1:8080/api/sprayer/on
curl -X POST http://127.0.0.1:8080/api/sprayer/off

# Старт / стоп місії
curl -X POST http://127.0.0.1:8080/api/mission/start
curl -X POST http://127.0.0.1:8080/api/mission/stop

# CV статус
curl http://127.0.0.1:8080/api/cv/status

# Геозона
curl http://127.0.0.1:8080/api/geofence
curl -X POST http://127.0.0.1:8080/api/geofence/set \
     -H "Content-Type: application/json" \
     -d '{"lat1":50.445,"lat2":50.455,"lon1":30.518,"lon2":30.530}'

# Моніторинг — зробити знімок зараз
curl -X POST http://127.0.0.1:8080/api/monitoring/sample

# Знахідки моніторингу
curl "http://127.0.0.1:8080/api/monitoring/findings?limit=20"

# Лог сесії
curl http://127.0.0.1:8080/api/diagnostics/session-log
```

---

## 9. Швидка довідка — де що змінити

| Що змінити | Файл | Ключ |
|------------|------|------|
| IP Pixhawk / radio | `config/system_gcs.yaml` | `mavlink.connection_px4` |
| Serial port RPi | `config/system_rpi.yaml` | `mavlink.connection_px4` |
| Порт GCS | `config/system.yaml` | `web.port` |
| Arrival radius (GPS) | `config/system.yaml` або `system_gcs.yaml` | `mission.arrival_radius_m` |
| Швидкість ровера | `config/system.yaml` | `mission.default_speed_m_s` |
| CV planner | `config/cv.yaml` | `planner: hybrid\|depth\|yolo` |
| CV джерело | `config/cv.yaml` | `source: video\|oakd\|webcam` |
| URL сервера аналізу | `config/monitoring.yaml` | `remote.base_url` |
| Оператор / станція | `config/monitoring.yaml` | `station.id`, `station.operator` |
| API ключ сервера | `config/server.yaml` | `api_key` |
| YOLO модель (сервер) | `config/server.yaml` | `models.vineyard` |
| Геозона за замовч. | `config/system.yaml` | `geofence.*` |

---

## Посилання

| Документ | Зміст |
|----------|-------|
| [`docs/PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) | Повний огляд системи та алгоритм роботи |
| [`docs/VARIANT_2_SETUP.md`](VARIANT_2_SETUP.md) | Детальне польове розгортання |
| [`docs/FIELD_DAY.md`](FIELD_DAY.md) | Чекліст польового дня |
| [`docs/MONITORING_REMOTE.md`](MONITORING_REMOTE.md) | Моніторинг: API, канали, offline-черга |
| [`docs/SIM_DEV.md`](SIM_DEV.md) | Розробка без заліза |
| [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) | Архітектурні рішення |
