import yaml


class MissionLoader:
    def __init__(self, path: str):
        self.path = path

    def load(self):
        with open(self.path, "r") as f:
            data = yaml.safe_load(f)
        return data["mission"]["waypoints"]
