
import json
import struct
from time import sleep

import awoxmeshlight
import paho.mqtt.client as mqtt

COMMAND_SLEEP = 0.04


class AwoXSmartLight(object):
    def __init__(self, _id, _gateway, _mqttc: mqtt.Client):
        self.id = _id
        self.gateway = _gateway
        self.mqtt_client: mqtt.Client = _mqttc

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
            self.publishAvailability()
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
            self.publishState()
            self.publishAvailability()
        else:
            if state_changed:
                print("From notification.", end="")
                self.publishState()
            elif availabilty_changed:
                print("Availabilty changed.")
                self.publishAvailability()
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

    def setPowerstate(self, value):
        if self.powerstate != value:
            if value == "ON":
                self.gateway.writeCommand(
                    awoxmeshlight.C_POWER, b'\x01', self.id)

                self.powerstate = "ON"
                print("Powerstate -> {}".format(value))
                sleep(COMMAND_SLEEP)
                return True
            elif value == "OFF":
                self.gateway.writeCommand(
                    awoxmeshlight.C_POWER, b'\x00', self.id)

                self.powerstate = "OFF"
                print("Powerstate -> {}".format(value))
                sleep(COMMAND_SLEEP)
                return True
            else:
                print("Unknown value for powerstate: {}".format(value))
                return False
        else:
            print("Already {}".format(self.powerstate))
            return False

    def setBrightness(self, value):
        if self.color_mode == "rgb":
            if self.color_brightness != value:
                adjusted = convert_value_to_available_range(
                    value, 3, 255, 1, 100)

                data = struct.pack('B', adjusted)
                self.gateway.writeCommand(
                    awoxmeshlight.C_COLOR_BRIGHTNESS, data, self.id)
                self.color_brightness = adjusted
                print("CB -> {}".format(adjusted))
                sleep(COMMAND_SLEEP)
                return True
            else:
                print("Already CB of {}".format(self.color_brightness))
                return False

        elif self.color_mode == "color_temp":
            if self.white_brightness != value:
                adjusted = convert_value_to_available_range(
                    value, 3, 255, 1, 127)

                data = struct.pack('B', adjusted)
                self.gateway.writeCommand(
                    awoxmeshlight.C_WHITE_BRIGHTNESS, data, self.id)
                self.white_brightness = adjusted
                print("WB -> {}".format(adjusted))
                sleep(COMMAND_SLEEP)
                return True
            else:
                print("Already WB of {}".format(self.white_brightness))
                return False
        else:
            print("Unknown color_mode: {}".format(self.color_mode))
            return False

    def setWhiteTemperature(self, temp):
        if self.color_mode == "rgb":
            adjusted = convert_value_to_available_range(temp, 153, 500, 0, 127)
            data = struct.pack('B', adjusted)
            self.gateway.writeCommand(
                awoxmeshlight.C_WHITE_TEMPERATURE, data, self.id)
            self.color_mode = "color_temp"
            self.white_temperature = adjusted
            print("CM -> {}, WT -> {}".format(self.color_mode, self.white_temperature))
            sleep(COMMAND_SLEEP)
            return True
        elif self.color_mode == "color_temp":
            if self.white_temperature != temp:
                adjusted = convert_value_to_available_range(
                    temp, 153, 500, 0, 127)
                data = struct.pack('B', adjusted)
                self.gateway.writeCommand(
                    awoxmeshlight.C_WHITE_TEMPERATURE, data, self.id)
                self.white_temperature = adjusted
                print("WB -> {}".format(self.white_temperature))
                sleep(COMMAND_SLEEP)
                return True
            else:
                print("Already WT of {}".format(self.white_temperature))
                return False
        else:
            print("Unknown color_mode: {}".format(self.color_mode))
            return False

    def setColor(self, rgb):
        print("--->", rgb)
        red = rgb["r"]
        green = rgb["g"]
        blue = rgb["b"]
        if self.color_mode == "color_temp":
            data = struct.pack('BBBB', 0x04, red, green, blue)
            self.gateway.writeCommand(awoxmeshlight.C_COLOR, data, self.id)
            self.color_mode = "rgb"
            self.red = red
            self.green = green
            self.blue = blue
            print("CM -> {}, RGB -> ({},{},{})".format(self.color_mode,
                  self.red, self.green, self.blue))
            sleep(COMMAND_SLEEP)
            return True
        elif self.color_mode == "rgb":
            if self.red == red and self.green == green and self.blue == blue:
                print("Already RGB of ({},{},{})".format(
                    self.red, self.green, self.blue))
                return False
            else:
                data = struct.pack('BBBB', 0x04, red, green, blue)
                self.gateway.writeCommand(awoxmeshlight.C_COLOR, data, self.id)
                self.red = red
                self.green = green
                self.blue = blue
                print("RGB -> ({},{},{})".format(self.red, self.green, self.blue))
                sleep(COMMAND_SLEEP)
                return True

        else:
            print("Unknown color_mode: {}".format(self.color_mode))
            return False

    def publishConfigMessage(self):
        config_topic = "homeassistant/light/{}/config".format(self.id)

        discovery_message = {
            "~": "homeassistant/light/{}".format(self.id),
            "name": self.id,
            "unique_id": "{}".format(self.id),
            "object_id": "{}".format(self.id),
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

    def publishState(self):
        light_state_topic = "homeassistant/light/{}/state".format(self.id)

        payload = self.getState()
        self.mqtt_client.publish(light_state_topic, json.dumps(payload))
        print("Publish state: {}".format(self))

    def publishAvailability(self):
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

    def execute_instruction(self, instruction):
        changed = False
        print(instruction)

        if "state" in instruction.keys():
            changed = self.setPowerstate(instruction["state"]) or changed
            # del instruction["state"]
        if "color_temp" in instruction.keys():
            changed = self.setWhiteTemperature(
                instruction["color_temp"]) or changed
            # del instruction["color_temp"]
        if "color" in instruction.keys():
            changed = self.setColor(instruction["color"]) or changed
            # del instruction["color"]
        if "brightness" in instruction.keys():
            changed = self.setBrightness(instruction["brightness"]) or changed
            # del instruction["brightness"]

        if changed:
            print("From broker.", end="")
            self.publishState()


def convert_value_to_available_range(value, min_from, max_from, min_to, max_to) -> int:
    normalized = (value - min_from) / (max_from - min_from)
    new_value = min(
        round((normalized * (max_to - min_to)) + min_to),
        max_to,
    )
    return max(new_value, min_to)
