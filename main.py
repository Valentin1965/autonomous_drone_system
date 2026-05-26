import argparse
import os
import sys
import threading
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.logger import setup_logger


def load_yaml(path: str):
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def start_simulator_background(system_cfg, logger):
    """MAVLink GPS/FC simulator in a daemon thread."""
    from mavlink.runtime_config import simulator_bind_string
    from simulator.pixhawk_simulator import PixhawkGPSSimulator

    bind = simulator_bind_string(system_cfg)
    logger.info(f"Симулятор (фон): {bind}")

    def _run():
        from simulator.registry import register

        sim = PixhawkGPSSimulator(bind)
        register(sim)
        sim.simulate_movement()

    t = threading.Thread(target=_run, name="pixhawk-sim", daemon=True)
    t.start()
    return t


def run_flask_server(system_cfg):
    from web.server import app

    web = system_cfg.get("web", {})
    host = web.get("host", "0.0.0.0")
    port = int(web.get("port", 8080))
    print(f"🌐 Flask: http://{host}:{port}  (локально http://127.0.0.1:{port})")
    app.run(host=host, port=port, debug=False, use_reloader=False)


def run_cv_mode(system_cfg, cv_source: str = None):
    from cv.tracker import YOLOSegmentationTracker, load_cv_config
    from web.motion_bridge import MotionBridge
    from web.state import drone_state

    cfg = load_cv_config()
    source = cv_source  # None = з config/cv.yaml (за замовч. video)
    print("🎥 CV трекер (motion in-process; потрібні --full або --web + симулятор)")
    tracker = YOLOSegmentationTracker(
        config=cfg, motion=MotionBridge(), source=source,
    )
    tracker.set_emergency_check(lambda: drone_state.emergency_stop)
    result = tracker.start()
    if isinstance(result, dict) and result.get("status") == "error":
        print(f"❌ CV не запущено: {result.get('message')}")
        return
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        tracker.stop()


def run_simulator_foreground(system_cfg, logger):
    from mavlink.runtime_config import simulator_bind_string
    from simulator.pixhawk_simulator import PixhawkGPSSimulator

    bind = simulator_bind_string(system_cfg)
    print(f"🧪 Симулятор (передній план): {bind}")
    sim = PixhawkGPSSimulator(bind, interactive=True)
    sim.simulate_movement()


def run_px4_mode(system_cfg, logger, run_mission: bool = False):
    from mavlink.ground_controller import GroundController
    from mavlink.runtime_config import client_connection_string, mavlink_profile
    from missions.mission_loader import MissionLoader
    from missions.mission_executor import MissionExecutor

    profile = mavlink_profile(system_cfg)
    conn_str = client_connection_string(system_cfg, profile)
    offboard = system_cfg.get("offboard", {})
    vehicle = system_cfg.get("vehicle", {})

    print(f"🚁 PX4 / автопілот [{profile}]: {conn_str}")
    ctrl = GroundController(
        connection_string=conn_str,
        rate_hz=offboard.get("rate_hz", 20),
        default_frame=vehicle.get("default_frame", "body"),
        heartbeat_timeout=system_cfg.get("mavlink", {}).get("heartbeat_timeout", 5),
        logger=logger,
    )
    ctrl.ensure_connected()
    print("✓ MAVLink підключено")

    if run_mission:
        mission_path = system_cfg.get("mission", {}).get("file", "config/mission.yaml")
        waypoints = MissionLoader(mission_path).load()
        ctrl.arm()
        MissionExecutor(ctrl.conn, logger).execute_local_mission(waypoints)
        ctrl.disarm()
        print("✓ Місію завершено")
        return

    print("Режим очікування (Ctrl+C). ARM/move — через Flask або API.")
    try:
        while True:
            st = ctrl.get_status()
            gps = st.get("gps") or {}
            if gps:
                print(
                    f"  lat={gps.get('lat', 0):.6f} lon={gps.get('lon', 0):.6f} "
                    f"armed={st['armed']}"
                )
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nЗупинка PX4 режиму...")


def run_full_stack(system_cfg, logger, with_cv_hint: bool = False):
    """Dev: симулятор у фоні + Flask на передньому плані."""
    start_simulator_background(system_cfg, logger)
    time.sleep(1.5)
    print("─" * 50)
    print("Dev stack: симулятор + веб-панель")
    print("  curl -X POST http://127.0.0.1:8080/api/arm")
    print('  curl -X POST http://127.0.0.1:8080/api/move -H "Content-Type: application/json" \\')
    print('       -d \'{"forward":0.5,"lateral":0,"yaw":0}\'')
    if with_cv_hint:
        print("  CV: http://127.0.0.1:8080/ → «Запустити YOLO»")
    print("─" * 50)
    run_flask_server(system_cfg)


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous Ground Rover System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Приклади:
  python main.py --simulator     # термінал 1: тільки симулятор
  python main.py --web           # термінал 2: Flask (симулятор окремо)
  python main.py --full          # один термінал: симулятор + Flask
  python main.py --px4 --mission # реальний / SITL PX4 + місія
        """,
    )
    parser.add_argument("--simulator", action="store_true", help="Симулятор MAVLink (foreground)")
    parser.add_argument("--web", action="store_true", help="Тільки Flask")
    parser.add_argument("--full", action="store_true", help="Симулятор (фон) + Flask")
    parser.add_argument("--px4", action="store_true", help="Підключення до PX4 / автопілота")
    parser.add_argument(
        "--mission",
        action="store_true",
        help="З --px4: виконати config/mission.yaml",
    )
    parser.add_argument("--cv", action="store_true", help="CV з config/cv.yaml (за замовч. video)")
    parser.add_argument("--cv-video", action="store_true", help="CV з відеофайлу (assets/videos/)")
    parser.add_argument("--cv-webcam", action="store_true", help="CV з USB-камери (після збірки)")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Як --full + підказка для CV",
    )
    args = parser.parse_args()

    modes = (
        args.simulator, args.web, args.full, args.px4,
        args.cv, args.cv_video, args.cv_webcam, args.all,
    )
    if not any(modes):
        parser.print_help()
        print("\n→ Швидкий старт:  python main.py --full")
        return

    system_cfg = load_yaml("config/system.yaml")
    logger = setup_logger(
        "autonomous_drone_system",
        system_cfg.get("logging", {}).get("level", "INFO"),
        system_cfg.get("logging", {}).get("log_dir", "logs"),
    )

    if args.full:
        run_full_stack(system_cfg, logger)
        return

    if args.all:
        run_full_stack(system_cfg, logger, with_cv_hint=True)
        return

    if args.simulator:
        run_simulator_foreground(system_cfg, logger)
        return

    if args.web:
        conn = system_cfg.get("mavlink", {}).get("connection_sim", "udp:127.0.0.1:14550")
        print(f"ℹ Очікується MAVLink на {conn} (запустіть: python main.py --simulator)")
        run_flask_server(system_cfg)
        return

    if args.px4:
        run_px4_mode(system_cfg, logger, run_mission=args.mission)
        return

    if args.cv or args.cv_video:
        run_cv_mode(system_cfg, cv_source="video" if args.cv_video else None)
        return
    if args.cv_webcam:
        run_cv_mode(system_cfg, cv_source="webcam")
        return


if __name__ == "__main__":
    main()
