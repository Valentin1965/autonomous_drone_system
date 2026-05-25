import argparse
import yaml
import threading
import time
import sys
import os

# Додаємо поточну директорію в PYTHONPATH
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.logger import setup_logger

# Імпорти
from simulator import PixhawkGPSSimulator
from mavlink.connection import MavlinkConnection
from mavlink.commander import Commander
from mavlink.offboard import OffboardController
from missions.mission_loader import MissionLoader
from missions.mission_executor import MissionExecutor

# CV модуль
from cv.yolov_tracker import YOLOSegmentationTracker

# Flask
from app import app


def load_yaml(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_flask_server():
    print("🌐 Запуск Flask веб-панелі на http://0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)


def run_cv_mode():
    print("🎥 Запуск YOLOv8 Segmentation Tracker...")
    tracker = YOLOSegmentationTracker()
    tracker.start()


def run_simulator_mode(logger):
    print("🧪 Запуск симулятора наземного дрона...")
    sim = PixhawkGPSSimulator('udpin:0.0.0.0:14550')
    sim.simulate_movement()


def run_px4_mode(system_cfg, logger):
    print("🚁 Запуск PX4 режиму...")
    # ... твій попередній код run_px4_mode ...
    pass


def main():
    parser = argparse.ArgumentParser(description="Autonomous Drone System")
    parser.add_argument("--simulator", action="store_true", help="Запустити симулятор")
    parser.add_argument("--px4", action="store_true", help="Запустити PX4 режим")
    parser.add_argument("--cv", action="store_true", help="Запустити тільки CV режим")
    parser.add_argument("--all", action="store_true", help="Запустити все (Flask + CV)")
    args = parser.parse_args()

    system_cfg = load_yaml("config/system.yaml")
    logger = setup_logger(
        "autonomous_drone_system",
        system_cfg.get("logging", {}).get("level", "INFO"),
        system_cfg.get("logging", {}).get("log_dir", "logs")
    )

    # Запуск Flask у фоновому потоці
    if args.all or not (args.simulator or args.px4 or args.cv):
        flask_thread = threading.Thread(target=run_flask_server, daemon=True)
        flask_thread.start()
        time.sleep(2)

    # Запуск вибраного режиму
    if args.simulator:
        run_simulator_mode(logger)
    elif args.px4:
        run_px4_mode(system_cfg, logger)
    elif args.cv:
        run_cv_mode()
    else:
        # Повний режим за замовчуванням
        print("🚀 Запуск у повному режимі (Flask + CV)")
        run_cv_mode()

    # Тримаємо головний потік
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n👋 Систему зупинено користувачем.")


if __name__ == "__main__":
    main()