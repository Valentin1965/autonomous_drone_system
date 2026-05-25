import argparse
import yaml
from utils.logger import setup_logger

from simulator import PixhawkGPSSimulator
from mavlink.connection import MavlinkConnection
from mavlink.commander import Commander
from mavlink.offboard import OffboardController
from missions.mission_loader import MissionLoader
from missions.mission_executor import MissionExecutor


def load_yaml(path: str):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def run_px4_mode(system_cfg, logger):
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

    import time
    time.sleep(5)

    mission_loader = MissionLoader("config/mission.yaml")
    waypoints = mission_loader.load()
    mission_executor = MissionExecutor(conn, logger=logger)
    mission_executor.execute_local_mission(waypoints)

    logger.info("Flying OFFBOARD square...")
    offboard.fly_square(size=5.0, alt=-3.0, loops=1)

    logger.info("Landing...")
    commander.land()
    time.sleep(5)

    logger.info("Disarming...")
    commander.disarm()


def run_simulator_mode(logger):
    logger.info("Запуск симулятора наземного дрона...")
    sim = PixhawkGPSSimulator('udpin:0.0.0.0:14550')
    sim.simulate_movement()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulator", action="true", help="Run ground rover simulator")
    parser.add_argument("--px4", action="true", help="Run PX4 SITL mode")
    args = parser.parse_args()

    system_cfg = load_yaml("config/system.yaml")
    log_cfg = system_cfg["logging"]
    logger = setup_logger("autonomous_drone_system", log_cfg["level"], log_cfg["log_dir"])

    if args.simulator:
        run_simulator_mode(logger)
    else:
        run_px4_mode(system_cfg, logger)


if __name__ == "__main__":
    main()
