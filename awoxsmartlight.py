
import json
import struct
from time import sleep

import awoxmeshlight_bleak
import paho.mqtt.client as mqtt

COMMAND_SLEEP = 0.04


class AwoXSmartLight(object):
    def __init__(self, _name, _id):
        self.name = _name
        self.id = _id

        self.color_mode = "color_temp"
        self.available = True
        self.powerstate = "ON"

        self.white_brightness = 77
        self.white_temperature = 102

        self.color_brightness = 60
        self.red = 255
        self.green = 0
        self.blue = 0
        self.publishConfigMessage()

    def setState(self, state, force_publish=False):
        state_changed = False
        availabilty_changed = False
        new_color_mode = self.modeFromNumerical(state["mode"])
        if self.color_mode != new_color_mode:
            self.color_mode = new_color_mode
            state_changed = True

        new_available = state["availability"] > 0
        if self.available != new_available:
            self.available = new_available
            self.publishAvailabilityMessage()
            availabilty_changed = True

        new_powerstate = "OFF" if state["status"] <= 0 else "ON"
        if self.powerstate != new_powerstate:
            self.powerstate = new_powerstate
            state_changed = True

        if self.white_brightness != state["white_brightness"]:
            self.white_brightness = state["white_brightness"]
            state_changed = True

        if self.white_temperature != state["white_temperature"]:
            self.white_temperature = state["white_temperature"]
            state_changed = True

        if self.color_brightness != state["color_brightness"]:
            self.color_brightness = state["color_brightness"]
            state_changed = True

        if self.red != state["red"]:
            self.red = state["red"]
            state_changed = True

        if self.green != state["green"]:
            self.green = state["green"]
            state_changed = True

        if self.blue != state["blue"]:
            self.blue = state["blue"]
            state_changed = True

        if force_publish:
            self.publishStateMessage()
            self.publishAvailabilityMessage()
        else:
            if state_changed:
                print("From notification.", end="")
                self.publishStateMessage()
            elif availabilty_changed:
                print("Availabilty changed.")
                self.publishAvailabilityMessage()
            else:
                print("Nothing changed.")

        print(self)

    def modeFromNumerical(self, mcode):
        # print("{:04d}".format(int(bin(mcode).replace("0b", ""))))
        mode = (mcode >> 1) % 2
        if mode == 0:
            return "color_temp"
        else:
            return "rgb"

    def __str__(self) -> str:
        return "Light {:>6s}: {:>3s}, WB: {:3d}, WT: {:3d}, CB: {:3d}, RGB: ({:03d},{:03d},{:03d}) color_mode: {:<10s}".format(
            ("" if self.available else "!") + str(self.id),
            self.powerstate,
            self.white_brightness,
            self.white_temperature,
            self.color_brightness,
            self.red, self.green, self.blue,
            self.color_mode)

    def publishConfigMessage(self):
        unique_id = "awox_{}".format(self.id)

        config_topic = "homeassistant/light/{}/config".format(unique_id)

        discovery_message = {
            "~": "homeassistant/light/{}".format(unique_id),
            "name": self.name,
            "unique_id": "awox_{}".format(unique_id),
            "command_topic": "~/set",
            "state_topic": "~/state",
            "availability_topic": "~/availability",
            "schema": "json",
            "brightness": True,
            "color_mode": True,
            "supported_color_modes": [
                "rgb", "color_temp"
            ]
        }
        self.mqtt_client.publish(config_topic, json.dumps(
            discovery_message), retain=True)

    def publishStateMessage(self):
        light_state_topic = "homeassistant/light/{}/state".format(self.id)

        payload = self.getState()
        self.mqtt_client.publish(light_state_topic, json.dumps(payload))
        print("Publish state: {}".format(self))

    def publishAvailabilityMessage(self):
        light_availability_topic = "homeassistant/light/{}/availability".format(
            self.id)
        payload = "online" if self.available else "offline"
        self.mqtt_client.publish(
            light_availability_topic, payload, retain=True)
        print("Publish availability: ({}) {}".format(self.id, payload))

    def getState(self):
        if self.color_mode == "rgb":
            brightness = convert_value_to_available_range(
                self.color_brightness, 1, 100, 3, 255)
        elif self.color_mode == "color_temp":
            brightness = convert_value_to_available_range(
                self.white_brightness, 1, 127, 3, 255)

        white_temperature = convert_value_to_available_range(
            self.white_temperature, 0, 127, 153, 500)

        state_dict = {
            "brightness": brightness,
            "color": {
                "r": self.red,
                "g": self.green,
                "b": self.blue,
            },
            "color_mode": self.color_mode,
            "color_temp": white_temperature,
            "state": self.powerstate,
        }

        return state_dict

    def executeInstruction(self, instruction):
        changed = False

        if "state" in instruction.keys():
            changed = self.setPowerstate(instruction["state"]) or changed

        if "color_temp" in instruction.keys():
            changed = self.setWhiteTemperature(
                instruction["color_temp"]) or changed

        if "color" in instruction.keys():
            changed = self.setColor(instruction["color"]) or changed

        if "brightness" in instruction.keys():
            changed = self.setBrightness(instruction["brightness"]) or changed

        if changed:
            print("From broker.", end="")
            self.publishStateMessage()
