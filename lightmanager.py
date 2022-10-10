"""Responsible for managing known lights and handling the communication with the lights. It keeps their state."""


import asyncio
import json
from queue import Queue
import threading
import paho.mqtt.client as mqtt
import struct
from awoxmeshlight_bleak import packetutils as pckt
from time import sleep
import awoxmeshlight_bleak
import bluepy.btle as btle
from awoxconnect import AwoxConnect

from awoxsmartlight import AwoXSmartLight

COMMAND_SLEEP = 0.4
MESH_GATEWAY = "a4:c1:38:1a:3b:2c"  # Schreibtisch
MESH_NAME = "FDCqrGLE"
MESH_PASSWD = "3588b7f4"

CLOUD_USERNAME = "a@peerdeman.info"
CLOUD_PASSWORD = "582YfW3NcLmK"

"""
LightManager is a class responsible for managing the connection to the AwoX Gateway.
The Gateway is the only lamp to which we keep a connection.
It will then pass commands into the mesh where the appropriate lamps will react.
The sending connection to the gateway is governed by a message queue to that we don't overwhelm the mesh.

The setup process is as follows:
We instanciate the object, fetch device information from the awox cloud.
We set up and connect to the gateway and query the mesh state.
This results in notifications which are handeled appropriately.

"""


class LightManager(object):
    def __init__(self, mqtt_client: mqtt.Client) -> None:
        self.known_lights = dict()
        self.message_queue = Queue()

        self._awox_data = None
        self._awox_credentials = None

        self.mqtt_client = mqtt_client

        # get data from AwoX Cloud
        # self.fetch_cloud()

        self.gateway: awoxmeshlight_bleak.AwoxMeshLight = None

        print("Connected to gateway.")

        # Delegate needs to be set after the connection is established because connect() overwrites it
        self.gateway.btdevice.setDelegate(MyDelegate(self))

    async def create(mqtt_client):
        lm = LightManager(mqtt_client)
        lm.gateway = awoxmeshlight_bleak.AwoxMeshLight(
            MESH_GATEWAY, MESH_NAME, MESH_PASSWD)

        await lm.gateway.connect()

        asyncio.create_task(lm.receive_notifications())
        asyncio.create_task(lm.send_commands())

        self.gateway.readStatus()
        return lm

    def receive_notifications(self):
        while True:
            print("Loop notification task")
            try:
                self.gateway.btdevice.waitForNotifications(timeout=None)
            except btle.BTLEException as e:
                print(e)

    def send_commands(self):
        while True:
            print("Waiting for message")
            message = self.message_queue.get()
            print("Got a message: ", message)

            print("Sleeping...")
            sleep(COMMAND_SLEEP)

    def queue_instruction(self, light, instruction):

        # selected_light.execute_instruction(instruction)
        # self.message_queue.put()
        pass

    def fetch_cloud(self):
        connect = AwoxConnect(CLOUD_USERNAME, CLOUD_PASSWORD)
        self._awox_data = connect.devices()
        self._awox_credentials = connect.credentials()
        print("Fetched AwoX Data")

    def pub_state(self, state):
        print("Publishing state: ", state)
        # Light state
        light_state_topic = "homeassistant/light/awox_{}/state".format(
            state["id"])
        payload = json.dumps(state["state"])
        self.mqtt_client.publish(
            light_state_topic, payload, retain=True)

        # Light availability
        light_availability_topic = "homeassistant/light/awox_{}/availability".format(
            state["id"])
        payload = json.dumps(state["availability"])
        self.mqtt_client.publish(
            light_availability_topic, payload, retain=True)

    def setPowerstate(self, value):
        if self.powerstate != value:
            if value == "ON":
                self.gateway.writeCommand(
                    awoxmeshlight_bleak.C_POWER, b'\x01', self.id)

                self.powerstate = "ON"
                print("Powerstate -> {}".format(value))
                sleep(COMMAND_SLEEP)
                return True
            elif value == "OFF":
                self.gateway.writeCommand(
                    awoxmeshlight_bleak.C_POWER, b'\x00', self.id)

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
                    awoxmeshlight_bleak.C_COLOR_BRIGHTNESS, data, self.id)
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
                    awoxmeshlight_bleak.C_WHITE_BRIGHTNESS, data, self.id)
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
                awoxmeshlight_bleak.C_WHITE_TEMPERATURE, data, self.id)
            self.color_mode = "color_temp"
            self.white_temperature = adjusted
            print("CM -> {}, WT -> {}".format(self.color_mode, self.white_temperature))
            sleep(COMMAND_SLEEP)
            return True
        elif self.color_mode == "color_temp":
            if self.white_temperature != temp:
                adjusted = convert_value_to_available_range(
                    temp, 153, 500, 0, 127)
                data = struct.pack(' B', adjusted)
                self.gateway.writeCommand(
                    awoxmeshlight_bleak.C_WHITE_TEMPERATURE, data, self.id)
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
            self.gateway.writeCommand(
                awoxmeshlight_bleak.C_COLOR, data, self.id)
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
                self.gateway.writeCommand(
                    awoxmeshlight_bleak.C_COLOR, data, self.id)
                self.red = red
                self.green = green
                self.blue = blue
                print("RGB -> ({},{},{})".format(self.red, self.green, self.blue))
                sleep(COMMAND_SLEEP)
                return True

        else:
            print("Unknown color_mode: {}".format(self.color_mode))
            return False


class MyDelegate(btle.DefaultDelegate):
    def __init__(self, _lightmanager: LightManager):
        btle.DefaultDelegate.__init__(self)
        self.lightmanager = _lightmanager

    def handleNotification(self, cHandle, data):
        message = pckt.decrypt_packet(
            self.lightmanager.gateway.session_key, self.lightmanager.gateway.mac, data)

        state, ok = self.parseMessage(message)
        if ok:
            self.lightmanager.pub_state(state)

    def applyState(self, state):
        light_id = state["id"]
        if light_id not in self.known_lights:
            new_light = AwoXSmartLight(
                light_id, self.gateway, self.mqtt_client)
            self.known_lights[light_id] = new_light
            new_light.setState(state, force_publish=True)
        else:
            changed_light = self.known_lights[light_id]
            changed_light.setState(state)

    def modeFromNumerical(self, mcode):
        # print("{:04d}".format(int(bin(mcode).replace("0b", ""))))
        mode = (mcode >> 1) % 2
        if mode == 0:
            return "color_temp"
        else:
            return "rgb"

    def parseMessage(self, message):
        unpacked = struct.unpack(20*'B', message)

        meshid = unpacked[3]
        mode = unpacked[12]

        # these messages represent something else
        if meshid != 0 or mode > 40:
            print("Unknown message: {}".format(unpacked))
            return None, False

        # light id
        right_ID = unpacked[10]
        left_ID = unpacked[19]
        light_id = (left_ID << 8) + right_ID

        # availability
        if unpacked[11] > 0:
            availability = "online"
        else:
            availability = "offline"

        # powerstate
        if (mode % 2) > 0:
            powerstate = "ON"
        else:
            powerstate = "OFF"

        # color_mode
        color_mode = self.modeFromNumerical(mode)

        # temperature
        color_temperature = convert_value_to_available_range(
            unpacked[14], 0, 127, 153, 500)

        # temperature Brightness
        white_brightness = convert_value_to_available_range(
            unpacked[13], 1, 127, 3, 255)

        # color Brightness
        color_brightness = convert_value_to_available_range(
            unpacked[15], 1, 100, 3, 255)

        # color_mode dependent brightness
        if color_mode == "rgb":
            brightness = color_brightness
        else:
            brightness = white_brightness

        # color
        red, green, blue = unpacked[16:19]

        return {
            "id": light_id,
            "availability": availability,
            "state": {
                "brightness": brightness,
                "color": {
                    "r": red,
                    "g": green,
                    "b": blue,
                },
                "color_mode": color_mode,
                "color_temp": color_temperature,
                "state": powerstate,
            }
        }, True


def convert_value_to_available_range(value, min_from, max_from, min_to, max_to) -> int:
    normalized = (value - min_from) / (max_from - min_from)
    new_value = min(
        round((normalized * (max_to - min_to)) + min_to),
        max_to,
    )
    return max(new_value, min_to)
