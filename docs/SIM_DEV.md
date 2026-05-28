# Розробка ПО без заліза (симулятор)

Поки немає Pixhawk / RPi / Oak-D, увесь стек запускається на ПК: **симулятор + GCS + CV на відео**.

**Чекліст стабільності (dev/sim):** [`SIM_STABILITY_CHECKLIST.md`](SIM_STABILITY_CHECKLIST.md)

---

## Швидкий старт

```bash
cd ~/autonomous_drone_system
source .venv/bin/activate
pip install -r requirements.txt

python main.py --full
# або (рекомендовано — analysis server + GCS):
bash scripts/run_sim_dev.sh
```

`run_sim_dev.sh`: `MONITORING_CONFIG=config/monitoring.dev.yaml`, **`remote.mode: remote`**, піднімає `python -m server.main` на `:8090`, потім `main.py --full`.

**Чекліст стабільності:** перед полем пройдіть [`SIM_STABILITY_CHECKLIST.md`](SIM_STABILITY_CHECKLIST.md).

Відкрийте **http://127.0.0.1:8080/**

| Крок | Дія |
|------|-----|
| 1 | **Флот** — оберіть Rover 1 / Rover 2 (якщо увімкнено в `config/system.yaml`) |
| 2 | **Редагувати: ВКЛ** → клікайте точки на карті (свій маршрут) |
| 3 | **Автономний** → **▶ Старт маршруту** |
| 4 | **Ручний** — лише для **обраного** дрона (стрілки) |
| 5 | Опційно: **Приклад маршруту** — завантажити готові 5 точок |
| 6 | **CV ряд (hybrid)** — відео в `assets/videos/*.mp4` або synthetic (див. нижче) |

### CV без відеофайлу

У `config/cv.yaml`: `source: video`, `fallback_to_synthetic: true` — якщо немає `.mp4`, трекер використовує синтетичний «ряд».

Пізніше на залізі: `source: oakd` у `config/cv_rpi.yaml`.

---

## Режими запуску

| Команда | Що робить |
|---------|-----------|
| `python main.py --full` | **Основний dev:** симулятор + GCS (+ флот з `system.yaml`) |
| `python main.py --simulator` | Тільки MAVLink-симулятор (термінал 1) |
| `python main.py --web` | Тільки GCS (термінал 2, потрібен симулятор) |
| `python main.py --all` | Як `--full` + підказка CV |

Конфіг: [`config/system.yaml`](../config/system.yaml)  
Приклад маршруту (кнопка в GCS): [`config/demo_mission.json`](../config/demo_mission.json)

---

## Флот (кілька дронів)

У `system.yaml` секція `fleet`:

- кожен дрон — свій `mavlink_connection` / `sim_bind`
- **свій маршрут**, автономний рух паралельно
- **ручне керування** — тільки **обраний** дрон

API: `GET /api/fleet`, `POST /api/fleet/select`, `?vehicle_id=` на mission API.

---

## API симулятора (dev)

| Метод | URL | Опис |
|-------|-----|------|
| POST | `/api/sim/load_demo` | Приклад маршруту (не автозавантаження) |
| POST | `/api/sim/reset` | Скинути позицію на точку 1 |

---

## Перехід на залізо (варіант 2)

1. [`VARIANT_2_SETUP.md`](VARIANT_2_SETUP.md)  
2. [`FIELD_DAY.md`](FIELD_DAY.md)  
3. `config/system_gcs.yaml` + `system_rpi.yaml`  
4. У полі: **не** `--full` — `scripts/run_variant2_*.sh`

---

## Документи

| Файл | Зміст |
|------|--------|
| [SIM_STABILITY_CHECKLIST.md](SIM_STABILITY_CHECKLIST.md) | Чекліст стабільності dev/sim (перед полем) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Архітектура |
| [FIELD_DAY.md](FIELD_DAY.md) | Поле |
