# Відео для CV (режим без камери)

Файли в цій папці **в .gitignore** (не потрапляють у git), але GCS/симулятор
**читають їх з диска** WSL: `~/autonomous_drone_system/assets/videos/`.

Покладіть сюди записи з рядів виноградника:

| Дрон (флот) | Файл |
|-------------|------|
| Rover 1 | `vineyard_demo.mp4` |
| Rover 2 | `vineyard_demo1.mp4` |
| Rover 3 | `vineyard_demo2.mp4` |
| Rover 4 | `vineyard_demo3.mp4` |
| Rover 5 | `vineyard_demo4.mp4` |

Формати: `.mp4`, `.avi`, `.mov`, `.mkv`

У `config/system.yaml` (секція `fleet`) або при зміні кількості дронів у GCS — поле `video_file` на кожен rover.  
Якщо `video_file` порожній — використовується перший файл у папці або `fallback_to_synthetic` у `config/cv.yaml`.

Перевірка:

```bash
python main.py --full
# GCS → оберіть Rover N → ▶ CV ряд (hybrid)
```

**NVIDIA MX130 / старі GPU:** у `config/cv.yaml` — `yolo_device: cpu` або `auto`.

Після підключення камер на полі — `config/cv_rpi.yaml`: `source: oakd`.
