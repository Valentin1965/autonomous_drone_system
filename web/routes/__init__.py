from flask import Flask

from web.routes.motion import motion_bp
from web.routes.telemetry import telemetry_bp
from web.routes.cv_api import cv_bp
from web.routes.sprayer import sprayer_bp
from web.routes.pages import pages_bp
from web.routes.mission_api import mission_bp


def register_routes(app: Flask) -> None:
    app.register_blueprint(motion_bp)
    app.register_blueprint(telemetry_bp)
    app.register_blueprint(cv_bp)
    app.register_blueprint(sprayer_bp)
    app.register_blueprint(mission_bp)
    app.register_blueprint(pages_bp)
