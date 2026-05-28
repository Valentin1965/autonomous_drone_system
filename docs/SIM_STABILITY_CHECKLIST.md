# Чекліст стабільності dev/sim

> **Пріоритет:** спочатку стабільний симулятор + GCS на ПК, **поле (варіант 2)** — після виконання цього чекліста.  
> Запуск: [`SIM_DEV.md`](SIM_DEV.md) · команди: [`RUN_COMMANDS.md`](RUN_COMMANDS.md)

---

## Ціль

Один запуск дає передбачувану поведінку:

```bash
cd ~/autonomous_drone_system
source .venv/bin/activate
python main.py --full
# → http://127.0.0.1:8080/
```

| Очікування | |
|------------|--|
| «Старт маршруту» і **Fleet ▶** | однакова логіка (waypoints, preflight, зупинка на останній точці) |
| CV hybrid | працює на `assets/videos/*.mp4` або synthetic без падінь |
| Моніторинг | `remote.mode: remote` + analysis server (`run_sim_dev.sh` або `python -m server.main`) |
| Регресії | ловляться `scripts/run_tests.sh` / CI, не вручну в браузері |

---

## 5 хвилин перед роботою (ручна перевірка)

Виконуйте після змін у коді або перед демо.

- [ ] **1. Старт стеку** — `python main.py --full` (або `bash scripts/run_sim_dev.sh`), GCS відкривається без помилок у терміналі
- [ ] **2. Один дрон** — «Редагувати: ВКЛ» → ≥2 точки → **Автономний** → **▶ Старт маршруту** → дрон доїжджає до кінця, фаза `at_last` / зупинка (не їде нескінченно)
- [ ] **3. Стоп** — **■ Стоп** або **STOP** зупиняє рух
- [ ] **4. Флот** (якщо `fleet.enabled: true` у `config/system.yaml`) — маршрути для Rover 1 і Rover 2 → **Fleet ▶** на кожному → обидва завершують маршрут
- [ ] **5. CV** — **▶ YOLO трекер** (відео або synthetic) → старт без fatal; **Стоп CV** зупиняє
- [ ] **6. Моніторинг** — **Зразок зараз** (mock) → знахідки з’являються в списку / на карті
- [ ] **7. Тести** — `bash scripts/run_tests.sh` — усі зелені

---

## Фаза 1 — Dev/sim (робота в репозиторії)

Позначайте `[x]` у цьому файлі або в PR, коли пункт зроблено.

### A. Автоматичні тести та CI

- [x] **A1.** CI запускає повний «легкий» набір: `bash scripts/run_tests.sh` (не лише 3 файли)
- [x] **A2.** Локально: `export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` + `bash scripts/run_tests.sh` проходить
- [x] **A3.** Інтеграційний тест: GCS → `POST /api/monitoring/sample` (mock remote) → findings (`tests/test_sim_monitoring_sample_e2e.py`)
- [x] **A4.** E2E fleet: 2 rover у sim, різні маршрути, обидва до `at_last` (`tests/test_sim_fleet_e2e.py`)
- [x] **A5.** Тест останньої точки місії (`tests/test_mission_last_stop.py`) при `arrival_radius_m` з `config/system.yaml`

### B. Місія та флот (симулятор)

- [x] **B1.** Fleet ▶ = «Старт маршруту»: `/api/fleet/mission/run` + `pushMissionWaypointsForVehicle`
- [x] **B2.** Preflight для fleet: `GET /api/preflight?vehicle_id=` + перевірка в UI перед Fleet ▶
- [ ] **B3.** `syncVehicleRouteStart` / snap до першої точки перед стартом — без «їде не з того місця» (ручна перевірка в GCS)
- [x] **B4.** Emergency stop блокує місію та CV (`tests/test_preflight_safety.py`)
- [x] **B5.** Hazard (CV) блокує рух місії (`tests/test_hazard_mission_pause.py`)

### C. CV у dev

- [x] **C1.** Без `.mp4` у `assets/videos/` — `fallback_to_synthetic: true` у `config/cv.yaml`, CV стартує
- [ ] **C2.** Після fatal у CV-циклі — рух зупиняється (`MotionBridge.stop`) — ручна перевірка
- [x] **C3.** У `SIM_DEV.md` зафіксовано: джерело `video` / `synthetic` / шлях до відео

### D. Моніторинг у dev

- [x] **D1.** Dev-профіль: `config/monitoring.dev.yaml` + `MONITORING_CONFIG` у `run_sim_dev.sh`
- [x] **D2.** GCS показує стан сервера: mock / remote + `/api/monitoring/remote/health`
- [ ] **D3.** (Опційно) другий термінал: `python scripts/start_analysis_server.py --port 8090`, `mode: remote`, sample проходить
- [x] **D4.** `GET /api/monitoring/queue` — статус outbox у UI + «Дослати чергу»

### E. UI та preflight

- [x] **E1.** Банер `#preflightBanner` з `block_reason` при `!ready_for_mission`
- [x] **E2.** Preflight у `GET /api/status` оновлюється разом із телеметрією
- [x] **E3.** Preflight для моніторингу: sample/survey + UI (`/api/monitoring/preflight`, банер у GCS)
- [ ] **E4.** Геозона (опційно в sim): встановити → старт за межами → відмова (ручна перевірка)

### F. Конфіг dev (не поле)

- [x] **F1.** `config/system.yaml`: `mission.arrival_radius_m: 1.0`
- [x] **F2.** `system_gcs.yaml` / `system_rpi.yaml` не змінювались (радіус 2.5 м — для поля)
- [x] **F3.** У полі **не** використовувати `python main.py --full` (зафіксовано в `FIELD_DAY.md`)

---

## Definition of Done — «sim стабільний»

Перехід на [варіант 2](VARIANT_2_SETUP.md) дозволений, коли **усі** пункти нижче виконані:

- [ ] `bash scripts/run_tests.sh` — зелений **локально** і в **CI**
- [ ] `python main.py --full`: один дрон → місія до `at_last` / зупинки на останній точці
- [ ] `python main.py --full`: fleet (2 дрони) → обидва завершують свої маршрути
- [ ] CV стартує на synthetic (без обов’язкового `.mp4`)
- [ ] Моніторинг **sample** у mock — findings у GCS
- [ ] (Рекомендовано) один раз: sample з `remote` на локальний `server.main:8090` — OK

---

## Фаза 2 — Поле (після Definition of Done)

**Не входить у поточний спринт dev/sim.** Чекліст поля — окремо:

| # | Задача | Документ |
|---|--------|----------|
| P1 | `POST /api/monitoring/upload` + `uplink.source: rpi` | [`MONITORING_REMOTE.md`](MONITORING_REMOTE.md) · `config/monitoring.field.yaml` |
| P2 | Оператор / станція у GCS + uplink на сервер | UI + `PUT /api/monitoring/station` |
| P3 | Офлайн-черга в UI (N у queue, flush) | `MONITORING_REMOTE.md` |
| P4 | `arrival_radius` у `system_gcs.yaml` (калібровка GPS) | [`VARIANT_2_SETUP.md`](VARIANT_2_SETUP.md) |
| P5 | `run_variant2_rpi.sh` / `run_variant2_gcs.sh`, preflight, systemd | [`VARIANT_2_SETUP.md`](VARIANT_2_SETUP.md) |
| P6 | SiK IP, mavlink-router, HTTPS/VPN | [`FIELD_DAY.md`](FIELD_DAY.md) |

---

## Корисні команди

```bash
# Стек dev
python main.py --full
bash scripts/run_sim_dev.sh

# Тести
bash scripts/run_tests.sh
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m pytest tests/ -q -m "not slow"

# Сервер аналізу (опційно, другий термінал)
python scripts/start_analysis_server.py --port 8090
curl http://127.0.0.1:8090/health

# Статус моніторинг-черги
curl http://127.0.0.1:8080/api/monitoring/queue
```

---

## Пов’язані документи

| Файл | Зміст |
|------|--------|
| [SIM_DEV.md](SIM_DEV.md) | Швидкий старт симулятора |
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | Огляд системи та алгоритми |
| [RUN_COMMANDS.md](RUN_COMMANDS.md) | Усі команди запуску |
| [VARIANT_2_SETUP.md](VARIANT_2_SETUP.md) | Поле — після sim |
| [FIELD_DAY.md](FIELD_DAY.md) | Польовий день |
