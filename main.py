import struct
import awoxmeshlight
import logging
import json
import paho.mqtt.client as mqtt

MESH_NAME = "FDCqrGLE"
MESH_PASSWORD = "3588b7f4"


def publish_discovery_message(client: mqtt.Client, unique_id, friendly_name):
    client.publish("homeassistant/light/{}/config".format(unique_id), json.dumps({
        "~": "homeassistant/light/"+unique_id,
        "name": friendly_name,
        "unique_id": unique_id,
        "command_topic": "~/set",
        "state_topic": "~/state",
        "schema": "json",
        "brightness": True,
        "color_mode": True,
        "supported_color_modes": [
            "rgb", "color_temp"
        ]
    }))


def match_message(client: mqtt.Client, message: mqtt.MQTTMessage):
    topic_parts = message.topic.split("/")
    unique_id = topic_parts[2]
    mac = unique_id.replace("-", ":")
    print(mac)
    payload = json.loads(message.payload)
    print(payload)

    execute_command(mac, payload, client)


def convert_value_to_available_range(value, min_from, max_from, min_to, max_to) -> int:
    normalized = (value - min_from) / (max_from - min_from)
    new_value = min(
        round((normalized * (max_to - min_to)) + min_to),
        max_to,
    )
    return max(new_value, min_to)


def pub_state(client: mqtt.Client, mac, state):
    client.publish(
        "homeassistant/light/{}/state".format(str(mac).replace(":", "-")), json.dumps(state))


def execute_command(mac, payload, client: mqtt.Client):
    mesh_id = mesh_ids[mac]
    light = light_state[mac]

    print(light)
    if "brightness" in payload:
        if light["color_mode"] == "rgb":
            print("set color brightness")
            requested = payload["brightness"]
            adjusted = convert_value_to_available_range(
                requested, 3, 255, int(0xa), int(0x64))

            data = struct.pack('B', adjusted)
            try:
                lightGateway.writeCommand(
                    awoxmeshlight.C_COLOR_BRIGHTNESS, data, mesh_id)
            except:
                print("error setting color brightness")
            light["state"] = "ON"
            light["brightness"] = requested

            pub_state(client, mac, {"brightness": requested, "state": "ON"})
            return
        elif light["color_mode"] == "color_temp":
            print("set white brightness")
            requested = payload["brightness"]
            adjusted = convert_value_to_available_range(
                requested, 3, 255, 1, int(0x7f))

            data = struct.pack('B', adjusted)
            try:
                lightGateway.writeCommand(
                    awoxmeshlight.C_WHITE_BRIGHTNESS, data, mesh_id)
            except:
                print("error setting white brightness")

            light["state"] = "ON"
            light["brightness"] = requested
            pub_state(client, mac, {"brightness": requested, "state": "ON"})
            return
        return

    if "color_temp" in payload:
        print("set temp")
        requestedTemp = payload["color_temp"]
        adjustedTemp = convert_value_to_available_range(
            requestedTemp, 153, 500, 0, int(0x7f))
        data = struct.pack('B', adjustedTemp)
        try:
            lightGateway.writeCommand(
                awoxmeshlight.C_WHITE_TEMPERATURE, data, mesh_id)
        except:
            print("error setting temp")
        light["color_mode"] = "color_temp"
        light["color_temp"] = requestedTemp
        light["state"] = "ON"
        pub_state(client, mac, {
            "color_mode": "color_temp",
            "color_temp": requestedTemp,
            "state": "ON",
        })
        return

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
        try:
            lightGateway.writeCommand(awoxmeshlight.C_COLOR, data, mesh_id)
        except:
            print("error setting color")

        light["color_mode"] = "rgb"
        light["color"] = {
            "r": reqRed,
            "g": reqGreen,
            "b": reqBlue,
        }
        light["state"] = "ON"

        pub_state(client, mac, {
            "color_mode": "rgb",
            "color": {
                "r": reqRed,
                "g": reqGreen,
                "b": reqBlue,
            },
            "state": "ON",
        })
        return

    if payload["state"] == "ON" and light["state"] == "OFF":
        print("turn on")
        try:
            lightGateway.writeCommand(awoxmeshlight.C_POWER, b'\x01', mesh_id)
        except:
            print("error turn on")
        light["state"] = "ON"

        pub_state(client, mac, {"state": "ON"})
        return

    if payload["state"] == "OFF" and light["state"] == "ON":
        print("turn off")
        try:
            lightGateway.writeCommand(awoxmeshlight.C_POWER, b'\x00', mesh_id)
        except:
            print("error turn off")
        light["state"] = "OFF"

        pub_state(client, mac, {"state": "OFF"})
        return


def on_connect(client: mqtt.Client, userdata, flags, rc):
    print("Connected with result code "+str(rc))

    client.subscribe("homeassistant/light/+/set")


def on_message(client: mqtt.Client, userdata, msg):
    print(msg.topic+" "+str(msg.payload))

    match_message(client, msg)


# ======
try:
    logger = logging.getLogger("awoxmeshlight")
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    with open("devices.json") as f:
        devices = json.load(f)

    for device in devices:
        if device["name"] == "Decke":
            lightGateway = awoxmeshlight.AwoxMeshLight(
                device["mac"], MESH_NAME, MESH_PASSWORD)
            lightGateway.connect()

    client = mqtt.Client()
    client.username_pw_set("mosquitto", "protocol-supervision-failed")
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect("192.168.0.32", 1883, 60)

    mesh_ids = {}
    light_state = {}

    for device in devices:
        if "light" in device["type"]:
            print(device)
            mesh_ids[device["mac"]] = device["mesh_id"]
            light_state[device["mac"]] = {
                "color_mode": "color_temp",
                "state": "OFF",
                "brightness": 255,
                "color": {
                    "r": 0,
                    "g": 0,
                    "b": 0,
                },
                "color_temp": "155"
            }
            publish_discovery_message(client, str(
                device["mac"]).replace(":", "-"), device["name"])

    client.loop_forever()
finally:
    print("Disconnecting.")
    lightGateway.disconnect()
    for device in devices:
        if "light" in device["type"]:
            client.publish(
                "homeassistant/light/{}/config".format(device["mac"]).replace(":", "-"), None)

    client.disconnect()
