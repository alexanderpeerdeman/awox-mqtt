import json
import logging
import struct
import time
import types

import awoxmeshlight
import bluepy
import paho.mqtt.client as mqtt
from awoxmeshlight import packetutils as pckt

MESH_NAME = "FDCqrGLE"
MESH_PASSWORD = "3588b7f4"

# receive message from mqtt -> apply to light // todo: find out if we can apply color_mode and brightness simultaneously
# receive notification from mesh -> apply to local state of light -> publish state

def publish_discovery_message(light):
    mesh_id = light["mesh_id"]
    client.publish("homeassistant/light/{}/config".format(mesh_id), json.dumps({
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
    }))


def match_message(message: mqtt.MQTTMessage):
    topic_parts = message.topic.split("/")
    print(topic_parts)
    mesh_id = int(topic_parts[2])
    if mesh_id in lights.keys():
        light = lights[mesh_id]

        payload = json.loads(message.payload)
        print("Executing a command on {}:\n{}".format(light, payload))
        execute_command(light, payload)


def convert_value_to_available_range(value, min_from, max_from, min_to, max_to) -> int:
    normalized = (value - min_from) / (max_from - min_from)
    new_value = min(
        round((normalized * (max_to - min_to)) + min_to),
        max_to,
    )
    return max(new_value, min_to)


def pub_state(light):
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

    r = convert_value_to_available_range(light["red"], 1, 127, 3, 255)
    g = convert_value_to_available_range(light["green"], 1, 127, 3, 255)
    b = convert_value_to_available_range(light["blue"], 1, 127, 3, 255)

    if light["status"] == 1:
        state = "ON"
    else:
        state = "OFF"

    payload = json.dumps({
        "brightness": brightness,
        "color": {
            "r": r,
            "g": g,
            "b": b,
        },
        "color_mode": color_mode,
        "color_temp": color_temp,
        "state": state
    })

    client.publish(
        "homeassistant/light/{}/state".format(light["mesh_id"]), payload)


def execute_command(light, payload):
    try:
        if "brightness" in payload:
            if light["mode"] == 8 or light["mode"] == 9:
                print("set white brightness")
                requested = payload["brightness"]
                adjusted = convert_value_to_available_range(
                    requested, 3, 255, 1, int(0x7f))

                data = struct.pack('B', adjusted)
                lightGateway.writeCommand(
                    awoxmeshlight.C_WHITE_BRIGHTNESS, data, light["mesh_id"])
            else:
                print("set color brightness")
                requested = payload["brightness"]
                adjusted = convert_value_to_available_range(
                    requested, 3, 255, int(0xa), int(0x64))

                data = struct.pack('B', adjusted)
                lightGateway.writeCommand(
                    awoxmeshlight.C_COLOR_BRIGHTNESS, data, light["mesh_id"])

        if "color_temp" in payload:
            print("set temp")
            requestedTemp = payload["color_temp"]
            adjustedTemp = convert_value_to_available_range(
                requestedTemp, 153, 500, 0, int(0x7f))
            data = struct.pack('B', adjustedTemp)
            lightGateway.writeCommand(
                awoxmeshlight.C_WHITE_TEMPERATURE, data, light["mesh_id"])

        if "color" in payload:
            print("set color")
            reqRed = payload["color"]["r"]
            reqGreen = payload["color"]["g"]
            reqBlue = payload["color"]["b"]
            adjRed = convert_value_to_available_range(
                reqRed, 0, 255, 0, int(0xff))
            adjGreen = convert_value_to_available_range(
                reqGreen, 0, 255, 0, int(0xff))
            adjBlue = convert_value_to_available_range(
                reqBlue, 0, 255, 0, int(0xff))

            data = struct.pack('BBBB', 0x04, adjRed, adjGreen, adjBlue)
            lightGateway.writeCommand(
                awoxmeshlight.C_COLOR, data, light["mesh_id"])

        if payload["state"] == "ON" and light["status"] == 0:
            print("turn on")
            lightGateway.writeCommand(
                awoxmeshlight.C_POWER, b'\x01', light["mesh_id"])

        if payload["state"] == "OFF" and light["status"] == 1:
            print("turn off")
            lightGateway.writeCommand(
                awoxmeshlight.C_POWER, b'\x00', light["mesh_id"])
    except bluepy.btle.BTLEInternalError as e:
        print("error:", e)


def on_connect(client: mqtt.Client, userdata, flags, rc):
    print("Connected with result code "+str(rc))

    client.subscribe("homeassistant/light/+/set")


def on_message(client: mqtt.Client, userdata, msg):
    print(msg.topic+" "+str(msg.payload))

    match_message(msg)


def myHandleNotification(self, cHandle, data):
    char = self.light.btdevice.getCharacteristics(cHandle)[0]
    if char.uuid == awoxmeshlight.STATUS_CHAR_UUID:
        logger.info("Notification on status char.")
        message = pckt.decrypt_packet(
            self.light.session_key, self.light.mac, data)
    else:
        logger.info("Receiced notification from characteristic %s",
                    char.uuid.getCommonName())
        message = pckt.decrypt_packet(
            self.light.session_key, self.light.mac, data)
        # logger.info("Received message : %s", repr(message))
        self.light.parseStatusResult(message)


def myParseStatusResult(self, message):
    meshid = struct.unpack('B', message[3:4])[0]
    for i, m in enumerate(struct.unpack('B'*len(message), message)):
        print("{:03d} ".format(m), end="")
    print("")
    
    idR = struct.unpack('B', message[10:11])[0]
    idL = struct.unpack('B', message[19:20])[0]
    integer_meshid = (idL << 8) + idR


    mode = struct.unpack('B', message[12:13])[0]
    if mode < 40 and meshid == 0:  # filter some messages that return something else
        if integer_meshid not in lights.keys():
            print("Need to set up light {}".format(integer_meshid))
            lights[integer_meshid] = {"mesh_id": integer_meshid}
            publish_discovery_message(lights[integer_meshid])
            # let homeassistant set up the device before sending state update
            time.sleep(0.25)
        light = lights[integer_meshid]

        light["mode"] = mode
        light["status"] = mode % 2

        light["white_brightness"] = struct.unpack('B', message[13:14])[0]
        light["white_temp"] = struct.unpack('B', message[14:15])[0]

        light["color_brightness"] = struct.unpack('B', message[15:16])[0]
        light["red"] = struct.unpack('B', message[16:17])[0]
        light["green"] = struct.unpack('B', message[17:18])[0]
        light["blue"] = struct.unpack('B', message[18:19])[0]

        print(json.dumps(light, indent=2, default=str))
        pub_state(light)


# ======
logger = logging.getLogger("awoxmeshlight")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)

client = mqtt.Client()
client.username_pw_set("mosquitto", "protocol-supervision-failed")
client.on_connect = on_connect
client.on_message = on_message

# Stehlampe
lightGateway = awoxmeshlight.AwoxMeshLight(
    "a4:c1:38:5b:22:89", MESH_NAME, MESH_PASSWORD)

# apply own handler functions to the library light object
lightGateway.parseStatusResult = types.MethodType(
    myParseStatusResult, lightGateway)
lightGateway.btdevice.delegate.handleNotification = types.MethodType(
    myHandleNotification, lightGateway)  # TODO this does nothing.

client.connect("192.168.0.32", 1883, 60)
lightGateway.connect()
lights = {}

# publish_discovery_message should be called when the light is first added to the array of
# light states. If the light goes offline we handle it differently (we dont delete it from HA)
# publish_discovery_message(client, light)
while True:
    try:
        if lightGateway.btdevice.waitForNotifications(0.25):
            continue
    except Exception as e:
        print("Error in loop:", e)
        pass

    client.loop(0.25)
