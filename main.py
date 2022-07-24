import json
import struct
import typing
from time import sleep

import awoxmeshlight
import paho.mqtt.client as mqtt
from awoxmeshlight import packetutils as pckt
from bluepy import btle

MESH_GATEWAY = "a4:c1:38:5b:22:89"
MESH_NAME = "FDCqrGLE"
MESH_PASSWD = "3588b7f4"

MQTT_BROKER = "192.168.0.32"
MQTT_USER = "mosquitto"
MQTT_PASSWD = "protocol-supervision-failed"

COMMAND_SLEEP = 0.001


class MyLight(object):
    def __init__(self, _id, _gateway, _mqttc):
        self.id = _id
        self.gateway = _gateway
        self.mqtt_client = _mqttc

        self.color_mode = "color_temp"
        self.available = True
        self.powerstate = "ON"

        self.white_brightness = 77
        self.white_temperature = 102

        self.color_brightness = 60
        self.red = 255
        self.green = 0
        self.blue = 0

    def setState(self, state):
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

        if state_changed:
            print("From notification.", end="")
            self.publishState()
        elif availabilty_changed:
            print("Availabilty changed.")
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

    def publishState(self):
        light_state_topic = "homeassistant/light/{}/state".format(self.id)

        payload = self.getState()
        self.mqtt_client.publish(light_state_topic, json.dumps(payload))
        print("Publish state: {}".format(self))

    def publishAvailability(self):
        light_availability_topic = "homeassistant/light/{}/availability".format(
            self.id)
        payload = "online" if self.available else "offline"
        self.mqtt_client.publish(light_availability_topic, payload)
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


def publish_discovery_message(light):
    mesh_id = light["mesh_id"]
    config_topic = "homeassistant/light/{}/config".format(mesh_id)
    payload = json.dumps({
        "~": "homeassistant/light/{}".format(mesh_id),
        "name": mesh_id,
        "unique_id": "{}".format(mesh_id),
        "object_id": "{}".format(mesh_id),
        "command_topic": "~/set",
        "state_topic": "~/state",
        "availability_topic": "~/availability",
        "schema": "json",
        "brightness": True,
        "color_mode": True,
        "supported_color_modes": [
            "rgb", "color_temp"
        ]
    })
    mqtt_client.publish(config_topic, payload, retain=True)


def convert_value_to_available_range(value, min_from, max_from, min_to, max_to) -> int:
    normalized = (value - min_from) / (max_from - min_from)
    new_value = min(
        round((normalized * (max_to - min_to)) + min_to),
        max_to,
    )
    return max(new_value, min_to)


def handle_set_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
    print("GOT {}: {}".format(msg.topic, msg.payload))
    topic_levels = msg.topic.split("/")
    target_light = int(topic_levels[2])

    if topic_levels[3] == "set" and target_light in known_lights:
        selected_light = known_lights[target_light]

        instruction = json.loads(msg.payload)
        selected_light.execute_instruction(instruction)


def on_connect(client: mqtt.Client, userdata, flags, rc):
    topic = "homeassistant/light/+/set"
    client.subscribe(topic)
    client.message_callback_add(topic, handle_set_message)


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
    print("No filter matched. Topic: {}, Message: {}".format(msg.topic, msg.payload))


class MyDelegate(btle.DefaultDelegate):
    def __init__(self, _gateway: awoxmeshlight.AwoxMeshLight, _lights: typing.Mapping[int, MyLight]):
        btle.DefaultDelegate.__init__(self)
        self.gateway = _gateway
        self.known_lights = _lights

    def handleNotification(self, cHandle, data):
        message = pckt.decrypt_packet(
            self.gateway.session_key, self.gateway.mac, data)

        # for _, m in enumerate(struct.unpack('B'*len(message), message)):
        #     print("{:03d} ".format(m), end="")
        # print()

        state, ok = self.parseMessage(message)
        if ok:
            self.applyState(state)

    def applyState(self, state):
        light_id = state["id"]
        if light_id not in self.known_lights:
            self.known_lights[light_id] = MyLight(
                light_id, self.gateway, mqtt_client)
        changed_light = self.known_lights[light_id]
        changed_light.setState(state)

    def parseMessage(self, message):
        unpacked = struct.unpack(20*'B', message)

        meshid = unpacked[3]
        mode = unpacked[12]

        # these messages represent something else
        if meshid != 0 or mode > 40:
            print("Unknown message: {}".format(unpacked))
            return None, False

        right_ID = unpacked[10]
        left_ID = unpacked[19]
        light_id = (left_ID << 8) + right_ID

        availability = unpacked[11]
        status = mode % 2

        white_brightness, white_temp = unpacked[13:15]

        color_brightness = unpacked[15]
        red, green, blue = unpacked[16:19]

        # print("ID: {:5d}, a: {:3d}, mode: {:2d}, status: {:1d}, WB: {:3d}, WT: {:3d}, CB: {:3d}, R: {:3d}, G: {:3d}, B: {:3d}\n".format(
        #     light_id, availability, mode, status, white_brightness, white_temp, color_brightness, red, green, blue))

        return {
            "id": light_id,
            "availability": availability,
            "mode": mode,
            "status": status,
            "white_brightness": white_brightness,
            "white_temperature": white_temp,
            "color_brightness": color_brightness,
            "red": red,
            "green": green,
            "blue": blue,
        }, True


mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWD)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

lightGateway = awoxmeshlight.AwoxMeshLight(
    MESH_GATEWAY, MESH_NAME, MESH_PASSWD)

mqtt_client.connect(MQTT_BROKER)
print("Connected to broker.")

known_lights = dict()

lightGateway.connect()
print("Connected to light gateway.")
lightGateway.btdevice.setDelegate(MyDelegate(lightGateway, known_lights))

while True:
    try:
        lightGateway.btdevice.waitForNotifications(0.01)

        mqtt_client.loop_read()
        mqtt_client.loop_misc()
        mqtt_client.loop_write()

    except btle.BTLEException as e:
        print(e)
