"""
Flask application — thin entry; routes in web/routes/.
"""

import yaml
from pathlib import Path

from flask import Flask

from web.routes import register_routes

app = Flask(__name__)
register_routes(app)


def _web_bind():
    from config.config_paths import system_config_path

    with open(system_config_path(), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    web = cfg.get("web", {})
    return web.get("host", "0.0.0.0"), int(web.get("port", 8080))


if __name__ == "__main__":
    host, port = _web_bind()
    print(f"=== Ground rover web panel http://{host}:{port} ===")
    app.run(host=host, port=port, debug=False)
