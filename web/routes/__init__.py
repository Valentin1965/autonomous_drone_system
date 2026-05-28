from flask import Flask

from web.routes.motion import motion_bp
from web.routes.telemetry import telemetry_bp
from web.routes.cv_api import cv_bp
from web.routes.sprayer import sprayer_bp
from web.routes.pages import pages_bp
from web.routes.mission_api import mission_bp
from web.routes.control_mode import control_bp
from web.routes.diagnostics import diagnostics_bp
from web.routes.sim_api import sim_bp
from web.routes.fleet_api import fleet_bp
from web.routes.geofence_api import geofence_bp
from web.routes.field_api import field_bp
from web.routes.monitoring_api import monitoring_bp
from web.routes.preflight_api import preflight_bp


def register_routes(app: Flask) -> None:
    app.register_blueprint(motion_bp)
    app.register_blueprint(control_bp)
    app.register_blueprint(telemetry_bp)
    app.register_blueprint(diagnostics_bp)
    app.register_blueprint(cv_bp)
    app.register_blueprint(sprayer_bp)
    app.register_blueprint(mission_bp)
    app.register_blueprint(sim_bp)
    app.register_blueprint(fleet_bp)
    app.register_blueprint(geofence_bp)
    app.register_blueprint(field_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(preflight_bp)
    app.register_blueprint(pages_bp)
