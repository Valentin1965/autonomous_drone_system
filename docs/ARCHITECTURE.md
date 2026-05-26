# Architecture — Autonomous Ground Rover System

**Production target:** [variant 2](VARIANT_2_SETUP.md) — RPi companion + Pixhawk + ground station.

## Decision record (Sprint 1)

| Topic | Decision |
|-------|----------|
| Vehicle type | **Ground rover** (MAVLink `MAV_TYPE_GROUND_ROVER`), not multicopter |
| Primary stack | **Python 3 + pymavlink + Flask** |
| Dev without hardware | **`simulator/pixhawk_simulator.py`** — emulates FC + GPS over UDP 14550 |
| Computer vision | **`cv/`** — YOLOv8; зараз **video files** (`assets/videos/`), далі Oak-D/webcam |
| Web control | **`web/`** — REST API + UI |
| ROS 2 (`src/drone_*`) | **Phase 2** — workspace builds in CI; not on the critical path for rover control |

## Layer diagram

```
┌─────────────────────────────────────────────────────────────┐
│  Operator / QGroundControl (optional, UDP 14550)            │
└───────────────────────────┬─────────────────────────────────┘
                            │ MAVLink
┌───────────────────────────▼─────────────────────────────────┐
│  Flight controller (real Pixhawk) OR PixhawkGPSSimulator    │
└───────────────────────────┬─────────────────────────────────┘
                            │ MAVLink (udp:127.0.0.1:14550)
┌───────────────────────────▼─────────────────────────────────┐
│  mavlink/ — connection, commander, offboard, ground_controller│
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  web/ — Flask API (arm, move, stop, CV, sprayer)            │
│  cv/  — row navigation (traversable / obstacle)               │
└─────────────────────────────────────────────────────────────┘
```

## Runtime modes (`main.py`)

| Flag | Purpose |
|------|---------|
| `--simulator` | `PixhawkGPSSimulator` (foreground) |
| `--web` | Flask only |
| `--full` | Simulator (background) + Flask — one terminal |
| `--all` | Like `--full` + CV hint |
| `--px4` | Connect to PX4/SITL |
| `--px4 --mission` | ARM + `config/mission.yaml` |
| `--cv` | CV + MotionBridge (needs `--web`/`--full`) |
| `--cv-webcam` | CV from USB camera |

Env `MAVLINK_PROFILE=px4` switches Flask to `connection_px4`.

## Web GCS (`web/templates/gcs.html`)

- Leaflet map + OSM tiles, rover trail
- Poll `GET /api/status` at 2 Hz
- Static assets: `web/static/css/gcs.css`, `web/static/js/gcs.js`

## Config

- `config/system.yaml` — MAVLink URL, offboard rate, web host/port
- `config/mission.yaml` — waypoint mission (LOCAL_NED; z = height reference for rover stack)
- `config/cv.yaml` — `source: video|oakd|webcam`, `video_dir`, classes

## Computer vision (`cv/tracker.py`)

- `YOLOSegmentationTracker` + **`cv/depth_row_planner.py`** (vineyard-style depth corridor)
- **`planner`** in `config/cv.yaml`: `yolo` | `depth` | **`hybrid`** (depth first, YOLO fallback)
- Pseudo-depth from RGB on video; real depth on Oak-D
- Motion via `web.motion_bridge.MotionBridge` → `GroundController` (no `requests` loopback)
- **Default:** `source: video` — files in `assets/videos/` (first `.mp4` if `video_file` empty)
- Later hardware: set `source: oakd` or `webcam`; env `CV_SOURCE=video|oakd|webcam`

## Deprecated

- **`vision/`** — stub detector; use **`cv/`** instead. See `vision/README.md`.

## Out of scope (Sprint 1)

- PX4 SITL in daily dev loop (documented in `Algorithm_autonomous_drone_system.md` for reference)
- MAVROS / ROS mission → PX4 bridge
- Aerial takeoff / altitude hold as primary workflow

## References

- Operational notes: `Algorithm_autonomous_drone_system.md`
- Refactor plan: discussed in project chat (Sprint 1, 5 days)
