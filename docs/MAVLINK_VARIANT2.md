# MAVLink — варіант 2 (RPi USB + GCS radio)

## Правило

| Вузол | Канал | Конфіг |
|-------|--------|--------|
| **RPi** (борт) | USB → Pixhawk | `system_rpi.yaml` → `mavlink.link: rpi_usb`, `connection_rpi: serial:...` |
| **GCS** (станція) | Radio / UDP телеметрія | `system_gcs.yaml` → `mavlink.link: gcs_radio`, `connection_gcs: udp:IP:14550` |

**Не підключайте GCS і RPi до одного й того ж порту FC одночасно без маршрутизатора** — будуть конфлікти heartbeat і команд.

## Рекомендована схема

```
Pixhawk ──USB──► RPi (CV, опційно companion)
    │
    └── TELEM radio ──► GCS ноутбук (Flask, місія, оператор)
```

- RPi: `scripts/run_variant2_rpi.sh` — `MAVLINK_PROFILE=px4`, serial only.
- GCS: `scripts/run_variant2_gcs.sh` — UDP на IP телеметрії.

## mavlink-router (якщо потрібні обидва)

На **RPi** (приклад):

```bash
# /etc/mavlink-router/main.conf
[UartEndpoint serial]
Device = /dev/ttyACM0
Baud = 115200

[UdpEndpoint gcs]
Mode = Normal
Address = 192.168.1.50
Port = 14550
```

GCS підключається до `udp:192.168.1.50:14550` (або IP RPi в Wi‑Fi), RPi — до serial. Деталі: [mavlink-router](https://github.com/mavlink-router/mavlink-router).

## Перевірка

```bash
# GCS
export SYSTEM_CONFIG=config/system_gcs.yaml MAVLINK_PROFILE=px4
python -c "from mavlink.runtime_config import mavlink_link_description, client_connection_string; from main import load_system_config; c=load_system_config(); print(mavlink_link_description(c)); print(client_connection_string(c))"

# RPi
export SYSTEM_CONFIG=config/system_rpi.yaml MAVLINK_PROFILE=px4
# те саме — має бути serial:/dev/ttyACM0:115200
```

У GCS HUD: **Connected** + оновлення Lat/Lon після ARM.
