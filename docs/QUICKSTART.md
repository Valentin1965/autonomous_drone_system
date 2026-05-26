# Quick start — 5 кроків

**Польове розгортання (варіант 2):** [`VARIANT_2_SETUP.md`](VARIANT_2_SETUP.md) · `scripts/run_variant2_gcs.sh` / `run_variant2_rpi.sh`

## 1. Середовище

```bash
cd ~/autonomous_drone_system
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pytest
```

Відео: `assets/videos/vineyard_demo.mp4`  
Модель: `yolov8s-seg.pt` у корені або `models/`

## 2. Запуск повного стеку

```bash
python main.py --full
```

Симулятор (фон) + **станція керування** http://127.0.0.1:8080/

- Карта OSM + трек руху rover
- **Відео CV** (MJPEG) — панель під картою, після ▶ YOLO
- HUD: ARM, GPS, швидкість, курс (оновлення ~2 Гц)
- D-pad рух, CV, оприскувач

## 3. ARM і рух

```bash
curl -X POST http://127.0.0.1:8080/api/arm
curl -X POST http://127.0.0.1:8080/api/move -H "Content-Type: application/json" \
     -d '{"forward":0.5,"lateral":0,"yaw":0}'
```

Або панель керування на http://127.0.0.1:8080/ (карта + телеметрія)

## 4. CV (відео)

У браузері: **▶ YOLO трекер**  
Або: `export YOLO_DEVICE=cpu` (для MX130) — вже `auto` у `config/cv.yaml`

## 5. Тести

```bash
pip install -r requirements-ci-light.txt
bash scripts/run_tests.sh
# повний CV-тест локально (потрібен ultralytics):
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
pytest tests/test_cv_motion.py -q
```

**WSL + ROS:** звичайний `pytest` підхоплює ROS-plugins → використовуйте `scripts/run_tests.sh` або `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.

## Пізніше (залізо)

`config/cv.yaml` → `source: oakd` або `webcam`  
`config/system.yaml` → `mavlink.active: px4`
