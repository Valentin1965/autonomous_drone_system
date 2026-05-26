# Відео для CV (режим без камери)

Покладіть сюди записи з рядів виноградника:

- `vineyard_demo.mp4` (або будь-яке ім’я)
- формати: `.mp4`, `.avi`, `.mov`, `.mkv`

У `config/cv.yaml` вже вказано `source: video`.  
Якщо `video_file` порожній — використовується **перший** файл у цій папці (за ім’ям).

Перевірка:

```bash
python main.py --full
# браузер → ▶ YOLO трекер
# або
python main.py --cv-video
```

**NVIDIA MX130 / старі GPU:** у `config/cv.yaml` — `yolo_device: cpu` або `auto` (автоматично CPU).

Після підключення камер змініть у `config/cv.yaml`:

```yaml
source: oakd    # Luxonis OAK-D
# або
source: webcam
```
