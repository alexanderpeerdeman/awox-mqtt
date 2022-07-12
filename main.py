import json
import logging
import struct
import types

import awoxmeshlight
import bluepy
import paho.mqtt.client as mqtt
from awoxmeshlight import packetutils as pckt

BLE_MESH_NAME = "FDCqrGLE"
BLE_MESH_PASSWORD = "3588b7f4"
MQTT_BROKER_HOST = "192.168.0.32"

# TODO: When changing more than just brightness or color (temperature), one of the commands is being swallowed.

# receive message from mqtt -> apply to light // todo: find out if we can apply color_mode and brightness simultaneously
# receive notification from mesh -> apply to local state of light -> publish state


def publish_discovery_message(light):
    mesh_id = light["mesh_id"]
    config_topic = "homeassistant/light/{}/config".format(mesh_id)
    payload = json.dumps({
        "~": "homeassistant/light/{}".format(mesh_id),
        # We dont know the lights names, that should be dealt with in HA.
        "name": mesh_id,
        # Hopefully the unique id lets this config survive restarts of the mqtt script.
        "unique_id": "{}".format(mesh_id),
        "object_id": "{}".format(mesh_id),
        "command_topic": "~/set",
        "state_topic": "~/state",
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


def publish_state(light):
    if light["mode"] == 8 or light["mode"] == 9:
        brightness = convert_value_to_available_range(
            light["white_brightness"], 1, 127, 3, 255)
        color_mode = "color_temp"
    else:
        brightness = convert_value_to_available_range(
            light["color_brightness"], 10, 100, 3, 255)
        color_mode = "rgb"
    color_temp = convert_value_to_available_range(
        light["white_temp"], 0, 127, 153, 500)

    if light["status"] == 1:
        state = "ON"
    else:
        state = "OFF"

    state_obj = {
        "brightness": brightness,
        "color": {
            "r": light["red"],
            "g": light["green"],
            "b": light["blue"],
        },
        "color_mode": color_mode,
        "color_temp": color_temp,
        "state": state
    }

    payload = json.dumps(state_obj)


    light_state_topic = "homeassistant/light/{}/state".format(light["mesh_id"])
    logger.debug("PUB {}: {}".format(light_state_topic, state_obj))
    mqtt_client.publish(light_state_topic, payload)


def execute_command(light, payload):
    logger.info("Light: {}".format(light))
    try:
        if "brightness" in payload:
            if light["mode"] == 8 or light["mode"] == 9:
                requested = payload["brightness"]
                adjusted = convert_value_to_available_range(
                    requested, 3, 255, 1, int(0x7f))

                logger.debug("set white brightness to {} (raw: {})".format(
                    adjusted, requested))
                data = struct.pack('B', adjusted)
                lightGateway.writeCommand(
                    awoxmeshlight.C_WHITE_BRIGHTNESS, data, light["mesh_id"])
            else:
                logger.debug("set color brightness")
                requested = payload["brightness"]
                adjusted = convert_value_to_available_range(
                    requested, 0, 255, int(0xa), int(0x64))

                data = struct.pack('B', adjusted)
                lightGateway.writeCommand(
                    awoxmeshlight.C_COLOR_BRIGHTNESS, data, light["mesh_id"])

        if "color_temp" in payload:
            logger.debug("set temp")
            requestedTemp = payload["color_temp"]
            adjustedTemp = convert_value_to_available_range(
                requestedTemp, 153, 500, 0, int(0x7f))
            data = struct.pack('B', adjustedTemp)
            lightGateway.writeCommand(
                awoxmeshlight.C_WHITE_TEMPERATURE, data, light["mesh_id"])

        if "color" in payload:
            logger.debug("set color")
            reqRed = payload["color"]["r"]
            reqGreen = payload["color"]["g"]
            reqBlue = payload["color"]["b"]
            # adjRed = convert_value_to_available_range(
            #     reqRed, 0, 255, 0, int(0xff))
            # adjGreen = convert_value_to_available_range(
            #     reqGreen, 0, 255, 0, int(0xff))
            # adjBlue = convert_value_to_available_range(
            #     reqBlue, 0, 255, 0, int(0xff))

            # logger.debug("set color to ({},{},{}) (raw: ({},{},{}))".format(
            #     adjRed, adjGreen, adjBlue, reqRed, reqGreen, reqBlue))

            data = struct.pack('BBBB', 0x04, reqRed, reqGreen, reqBlue)
            lightGateway.writeCommand(
                awoxmeshlight.C_COLOR, data, light["mesh_id"])

        if payload["state"] == "ON" and light["status"] == 0:
            logger.debug("turn on")
            lightGateway.writeCommand(
                awoxmeshlight.C_POWER, b'\x01', light["mesh_id"])

        if payload["state"] == "OFF" and light["status"] == 1:
            logger.debug("turn off")
            lightGateway.writeCommand(
                awoxmeshlight.C_POWER, b'\x00', light["mesh_id"])
    except bluepy.btle.BTLEInternalError as e:
        print("Error while executing a command: {}".format(e))


def on_connect(client: mqtt.Client, userdata, flags, rc):
    logger.info("Connected with result code "+str(rc))

    client.subscribe("homeassistant/light/+/set")
    client.subscribe("homeassistant/status")


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
    logger.info("MSG {}: {}".format(msg.topic, msg.payload))
    sub_topics = msg.topic.split("/")
    if len(sub_topics) == 2 and sub_topics[1] == "status":
        if msg.payload == b'online':
            # re-announce all lights
            for light in lights.values():
                publish_discovery_message(light)
                publish_state(light)
        return
    mesh_id = int(sub_topics[2])
    if sub_topics[3] == "set" and mesh_id in lights.keys():
        light = lights[mesh_id]

        payload = json.loads(msg.payload)
        logger.info("Payload: {}".format(payload))
        execute_command(light, payload)
        return


class MyDelegate(bluepy.btle.DefaultDelegate):
    def __init__(self):
        bluepy.btle.DefaultDelegate.__init__(self)
        # initialize here

    def handleNotification(self, cHandle, data):
        try:
            char = self.light.btdevice.getCharacteristics(cHandle)[0]
            if char.uuid == awoxmeshlight.STATUS_CHAR_UUID:
                logger.debug("Notification on status char.")
                message = pckt.decrypt_packet(
                    self.light.session_key, self.light.mac, data)
            else:
                logger.debug("Receiced notification from characteristic %s",
                             char.uuid.getCommonName())
                message = pckt.decrypt_packet(
                    self.light.session_key, self.light.mac, data)
                # logger.info("Received message : %s", repr(message))
                self.light.parseStatusResult(message)
        except:
            pass


def myParseStatusResult(self, message):
    meshid = struct.unpack('B', message[3:4])[0]

    right_ID = struct.unpack('B', message[10:11])[0]
    left_ID = struct.unpack('B', message[19:20])[0]
    integer_meshid = (left_ID << 8) + right_ID

    mode = struct.unpack('B', message[12:13])[0]
    if mode < 40 and meshid == 0:  # filter some messages that return something else
        if integer_meshid not in lights.keys():
            logger.info("Need to set up light {}".format(integer_meshid))
            lights[integer_meshid] = {"mesh_id": integer_meshid}
            publish_discovery_message(lights[integer_meshid])
        light = lights[integer_meshid]

        light["mode"] = mode
        light["status"] = mode % 2

        light["white_brightness"] = struct.unpack('B', message[13:14])[0]
        light["white_temp"] = struct.unpack('B', message[14:15])[0]

        light["color_brightness"] = struct.unpack('B', message[15:16])[0]
        light["red"] = struct.unpack('B', message[16:17])[0]
        light["green"] = struct.unpack('B', message[17:18])[0]
        light["blue"] = struct.unpack('B', message[18:19])[0]

        logger.info(json.dumps(light, indent=2, default=str))
        publish_state(light)


# ======
logger = logging.getLogger("awoxmeshlight")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)

mqtt_client = mqtt.Client()
mqtt_client.username_pw_set("mosquitto", "protocol-supervision-failed")
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# Decke
lightGateway = awoxmeshlight.AwoxMeshLight(
    "a4:c1:38:35:d1:8c", BLE_MESH_NAME, BLE_MESH_PASSWORD)

# apply own handler functions to the library light object
lightGateway.parseStatusResult = types.MethodType(
    myParseStatusResult, lightGateway)

lightGateway.btdevice.setDelegate(MyDelegate())

mqtt_client.connect(MQTT_BROKER_HOST)

lightGateway.connect()
lights = {}

# publish_discovery_message should be called when the light is first added to the array of
# light states. If the light goes offline we handle it differently (we dont delete it from HA)
# publish_discovery_message(client, light)
while True:
    try:
        lightGateway.btdevice.waitForNotifications(timeout=0.1)

        mqtt_client.loop_read()
        mqtt_client.loop_write()
        mqtt_client.loop_misc()
    except bluepy.btle.BTLEInternalError as e:
        logger.info("Error while handling a notification: {}".format(e))
        pass
    except KeyboardInterrupt:
        print("Stop")
        break
