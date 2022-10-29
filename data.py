from dataclasses import asdict, dataclass
from enum import Enum
import json


class ColorMode(str, Enum):
    RGB = "rgb"
    COLOR_TEMP = "color_temp"


class PowerState(str, Enum):
    ON = "ON"
    OFF = "OFF"


class Availability(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"


@dataclass
class ColorData:
    r: int
    g: int
    b: int


@dataclass
class StateData:
    brightness: int
    color: ColorData
    color_mode: ColorMode
    color_temp: int
    state: PowerState

    def json(self):
        return json.dumps(asdict(self))
