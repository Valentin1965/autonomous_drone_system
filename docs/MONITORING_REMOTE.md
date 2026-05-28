# Система моніторингу — архітектура та API

## Структура блоків

```
┌─────────────────────────────────────────────────────────────────────┐
│  ДРОН (RPi + Pixhawk)                                               │
│  ┌─────────────────┐   USB serial (MAVLink)                         │
│  │  Pixhawk        │─────────────────────────────────────────────►  │
│  │  GPS / рух      │                                                 │
│  └─────────────────┘                                                 │
│  ┌─────────────────┐   Wi-Fi 5 GHz → JPEG                           │
│  │  RPi + камери   │──────────────────────────────────────────────► │
│  │  L / R          │                                                 │
│  └─────────────────┘                                                 │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ (два потоки)
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  СТАНЦІЯ GCS  (ноутбук / польовий планшет)                           │
│                                                                       │
│  python main.py --full  →  http://GCS:8080                            │
│                                                                       │
│  • Карта Leaflet, маршрут, fleet                                      │
│  • monitoring/  — зйомка L/R (local або від RPi)                     │
│  • Локальний кеш знахідок: data/monitoring/findings.json             │
│  • Офлайн-черга: data/monitoring/outbox/  (якщо 5G пропав)          │
│                                                                       │
│  Канал до сервера: 5G-модем → інтернет → HTTPS                       │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTPS (один бік: тільки вгору)
                                │  POST /api/v1/analyze   (JPEG + контекст)
                                │  POST /api/v1/events    (маршрут, spray…)
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  СЕРВЕР АНАЛІЗУ  (окремий блок, один на N станцій)                   │
│                                                                       │
│  python -m server.main --port 8090                                   │
│  або: python scripts/start_analysis_server.py                        │
│                                                                       │
│  • YOLOv8 — inference по знімках                                     │
│  • SQLite  — повна база роботи флоту:                                │
│      fleet_events          — де, коли, що робили                     │
│      monitoring_captures   — знімки, GPS, культура, оператор         │
│      monitoring_detections — висновки YOLO                           │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Канали зв'язку

| Пара | Канал | Тип трафіку |
|------|-------|-------------|
| Дрон Pixhawk ↔ GCS | **868 MHz SiK radio** (MAVLink) | керування, GPS, failsafe |
| RPi камери → GCS | **Wi-Fi 5 GHz** (HTTP POST JPEG) | знімки моніторингу L/R |
| GCS → Сервер | **5G-модем → інтернет → HTTPS** | JPEG + контекст, події флоту |

**Дані йдуть лише вгору** (моніторинг): дрон → станція → сервер.  
Назад сервер повертає лише відповідь JSON із висновками (HTTP response).

---

## Запуск

### Сервер (окремо, один раз)

```bash
# Dev (без YOLO, лише БД)
python -m server.main --port 8090

# З реальними вагами
python scripts/start_analysis_server.py --port 8090 \
  --vineyard-weights /path/to/vineyard.pt \
  --device cpu
```

Конфіг сервера: `config/server.yaml`

### Станція

```bash
python main.py --full   # → http://127.0.0.1:8080/
```

У `config/monitoring.yaml` встановити:
```yaml
remote:
  mode: remote          # замість mock
  base_url: "http://SERVER_IP:8090"
station:
  id: gcs-1
  operator: "Ім'я оператора"
```

---

## config/monitoring.yaml — ключові секції

### `uplink` — звідки йдуть камери на станцію

```yaml
uplink:
  source: local       # local = камери прямо на GCS
                      # rpi   = RPi надсилає JPEG по Wi-Fi 5 GHz
  rpi:
    host: "192.168.1.20"
    port: 8081
    upload_path: "/api/monitoring/upload"
    wait_timeout_s: 10.0
    upload_token: ""   # опційно: заголовок X-Upload-Token
    wifi_band: "5GHz"
  to_server:
    channel: "5G_modem"
```

**RPi → станція:** `POST /api/monitoring/upload` (multipart: `vehicle_id`, `side=left|right`, `image`).

```bash
python scripts/rpi_monitoring_upload.py \
  --gcs http://192.168.1.50:8080 --vehicle rover_1 --side left --image /tmp/left.jpg
```

Польовий профіль GCS: `config/monitoring.field.yaml` (`run_variant2_gcs.sh`).

### Станція / оператор

- `GET/PUT /api/monitoring/station` — збереження в `config/monitoring_runtime.yaml`
- Поля в GCS: блок **Моніторинг** → Станція / Оператор

### Preflight моніторингу

- `GET /api/monitoring/preflight?vehicle_id=` — те саме, що `ready_for_cv` (ARM, GPS, e-stop)
- Перед **Зразок** / **Обстеження** — перевірка в UI і на API (`409 preflight_failed`)

### `offline_queue` — черга при відсутності 5G

```yaml
offline_queue:
  enabled: true
  queue_dir: data/monitoring/outbox
  retry_interval_s: 30   # перевіряти кожні 30 с
  max_retries: 0          # 0 = нескінченно
  max_queue_size: 500
  flush_delay_s: 0.5
```

---

## Офлайн-черга (опис роботи)

```
Станція намагається POST → Сервер
       │
       ├─ Успішно ────────────────────► response → findings.json → карта GCS
       │
       └─ Немає зв'язку (5G пропав)
             │
             ▼
    data/monitoring/outbox/
      <ts>_<id>_event.json          ← подія флоту
      <ts>_<id>_capture.json        ← метадані знімка
      <ts>_<id>_capture_left.jpg    ← JPEG
      <ts>_<id>_capture_right.jpg   ← JPEG
             │
             │  retry-воркер перевіряє кожні retry_interval_s
             │  при GET /health → 200:
             ▼
    Flush черги → POST на сервер → видалити файли
```

Статус черги: `GET /api/monitoring/queue`  
Примусовий flush: `POST /api/monitoring/queue/flush`

---

## API сервера аналізу

### `GET /` — стан і список endpoint

### `GET /health`

```json
{
  "status": "ok",
  "service": "fleet-analysis-server",
  "models_loaded": ["vineyard"],
  "database": { "fleet_events": 42, "monitoring_captures": 15, "monitoring_detections": 38, "stations_seen": 2 }
}
```

### `POST /api/v1/analyze` — знімки + контекст

`multipart/form-data`:

| Поле | Тип | Опис |
|------|-----|------|
| `left_image` | file JPEG | Ліва камера |
| `right_image` | file JPEG | Права камера |
| `crop` | string | `vineyard` / `banana` |
| `vehicle_id` | string | ID дрона |
| `station_id` | string | ID станції |
| `operator` | string | Ім'я оператора |
| `lat`, `lon` | float | GPS знімка |
| `source` | string | `survey` / `manual` |
| `capture_id` | string | UUID знімка |
| `context_json` | JSON string | Стан дрона: місія, spray, work_record |

Відповідь:
```json
{
  "status": "ok",
  "capture_id": "abc123",
  "detections": [
    { "camera": "left", "label": "downy_mildew", "confidence": 0.72, "issue_type": "disease", "severity": "medium" }
  ],
  "stored": true,
  "message": "Analyzed 2 image(s) — 1 detection(s)"
}
```

### `POST /api/v1/events` — подія без фото

JSON-тіло:
```json
{
  "station_id": "gcs-1",
  "operator": "Петро",
  "vehicle_id": "rover_1",
  "event_type": "mission_run",
  "detail": "5 точок @ 1.0 m/s",
  "lat": 50.45, "lon": 30.52,
  "payload": { "waypoint_count": 5, "vehicle_context": {} }
}
```

Типи подій: `mission_run`, `sprayer_on`, `sprayer_off`, `monitoring_survey_start`, `monitoring_survey_end`, `monitoring_capture` (авто, від `/analyze`).

**Spray ↔ моніторинг:** під час `sprayer_on` … `sprayer_off` станція збирає GPS-трек; у `sprayer_off` у `payload.spray_coverage` — довжина (м), площа (м², га), час. Контекст зйомки (`context_json`) містить `vehicle.spray_coverage`. На сервері: `GET /api/v1/spray/coverage` — сесії + зв’язок із findings; дашборд `/dashboard`.

### `GET /api/v1/findings`

Query: `station_id`, `vehicle_id`, `crop`, `limit`

### `GET /api/v1/operations`

Query: `station_id`, `vehicle_id`, `event_type`, `limit`

### `GET /api/v1/stats`

```json
{ "fleet_events": 100, "monitoring_captures": 40, "monitoring_detections": 95, "stations_seen": 3 }
```

### `GET /dashboard`

Проста HTML-сторінка (таблиці знахідок і журналу операцій). Дані з тих самих API; при `api_key` на сервері — поле Bearer у шапці (зберігається в `sessionStorage`).

Відкрити: `http://127.0.0.1:8090/dashboard`

---

## База даних сервера (SQLite)

| Таблиця | Зберігає |
|---------|----------|
| `fleet_events` | де, коли, що робили; маршрут, spray, обстеження, оператор, payload |
| `monitoring_captures` | GPS, культура, шляхи до JPEG, контекст дрона, станція |
| `monitoring_detections` | висновки YOLO по кожному знімку |

Ключові поля `fleet_events.payload_json`:
- `vehicle_context.mission.phase` — фаза місії в момент події
- `vehicle_context.work_record` — журнал роботи (spray, нотатки)
- `fleet_snapshot` — знімок стану всього флоту

---

## Безпека / авторизація

Якщо сервер запущено з `--api-key secret`:
- Станція: `remote.api_key: secret` в `config/monitoring.yaml`
- Header: `Authorization: Bearer secret`

Рекомендовано додати HTTPS (nginx reverse proxy або VPN WireGuard між станцією та сервером).
