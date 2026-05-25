import argparse
import yaml
import threading
import time
from utils.logger import setup_logger

# Імпорти основних модулів
from simulator import PixhawkGPSSimulator
from mavlink.connection import MavlinkConnection
from mavlink.commander import Commander
from mavlink.offboard import OffboardController
from missions.mission_loader import MissionLoader
from missions.mission_executor import MissionExecutor

# Імпорт CV модуля
from cv.yolov8_tracker import YOLOSegmentationTracker

# Flask сервер
from app import app  # ← твій основний Flask файл

def load_yaml(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_flask_server():
    """Запуск Flask веб-панелі"""
    print("🚀 Запуск Flask веб-сервера на http://0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)


def run_px4_mode(system_cfg, logger):
    """Режим роботи з реальним PX4 / SITL"""
    logger.info("=== PX4 РЕЖИМ ЗАПУЩЕНО ===")
    
    conn_cfg = system_cfg["mavlink"]
    conn = MavlinkConnection(
        connection_string=conn_cfg["connection_string"],
        heartbeat_timeout=conn_cfg["heartbeat_timeout"],
        logger=logger,
    )
    conn.connect()

    commander = Commander(conn, logger=logger)
    offboard = OffboardController(conn, rate_hz=system_cfg["offboard"]["rate_hz"], logger=logger)

    logger.info("Arming...")
    commander.arm()

    logger.info("Takeoff...")
    commander.takeoff(system_cfg["offboard"]["default_altitude"])
    time.sleep(6)

    # Виконання місії
    mission_loader = MissionLoader("config/mission.yaml")
    waypoints = mission_loader.load()
    mission_executor = MissionExecutor(conn, logger=logger)
    mission_executor.execute_local_mission(waypoints)

    logger.info("Виконання Offboard square...")
    offboard.fly_square(size=5.0, alt=-3.0, loops=1)

    logger.info("Landing...")
    commander.land()
    time.sleep(6)

    logger.info("Disarming...")
    commander.disarm()


def run_simulator_mode(logger):
    """Режим симулятора"""
    logger.info("=== ЗАПУСК СИМУЛЯТОРА НАЗЕМНОГО ДРОНА ===")
    sim = PixhawkGPSSimulator('udpin:0.0.0.0:14550')
    sim.simulate_movement()


def run_cv_mode(logger):
    """Запуск CV трекера (YOLOv8 + Oak-D)"""
    logger.info("=== ЗАПУСК COMPUTER VISION MODE ===")
    tracker = YOLOSegmentationTracker()
    tracker.start()


def main():
    parser = argparse.ArgumentParser(description="Autonomous Drone System")
    parser.add_argument("--simulator", action="store_true", help="Запустити симулятор наземного дрона")
    parser.add_argument("--px4", action="store_true", help="Запустити PX4 / SITL режим")
    parser.add_argument("--cv", action="store_true", help="Запустити тільки CV режим (YOLOv8 + Oak-D)")
    parser.add_argument("--all", action="store_true", help="Запустити все: Flask + CV + PX4/Simulator")
    args = parser.parse_args()

    # Завантаження конфігурації
    system_cfg = load_yaml("config/system.yaml")
    logger = setup_logger(
        "autonomous_drone_system", 
        system_cfg["logging"]["level"], 
        system_cfg["logging"]["log_dir"]
    )

    # Запуск Flask сервера в окремому потоці (якщо потрібно)
    if args.all or not (args.simulator or args.px4 or args.cv):
        flask_thread = threading.Thread(target=run_flask_server, daemon=True)
        flask_thread.start()
        time.sleep(1.5)  # Даємо Flask запуститися

    # Виконання вибраного режиму
    if args.simulator:
        run_simulator_mode(logger)
    elif args.px4:
        run_px4_mode(system_cfg, logger)
    elif args.cv:
        run_cv_mode(logger)
    else:
        # За замовчуванням — повний режим
        logger.info("Запуск у повному режимі (Flask + CV)")
        run_cv_mode(logger)          # Запускаємо CV трекер
        # run_px4_mode(system_cfg, logger)  # або симулятор — за потреби

    # Тримаємо головний потік живим
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Систему зупинено користувачем.")


if __name__ == "__main__":
    main()