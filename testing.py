import asyncio
import json
import struct
from bluepy import btle
from time import sleep
import paho.mqtt.client as mqtt

import awoxmeshlight_bluepy


# MESH_GATEWAY = "A4:C1:38:1A:CA:39"  # Schrank
# MESH_GATEWAY = "A4:C1:38:35:D1:8C"  # Decke
MESH_GATEWAY = "A4:C1:38:1A:3B:2C"  # Schreibtisch
MESH_NAME = "FDCqrGLE"
MESH_PASSWD = "3588b7f4"

# MQTT_BROKER = "localhost"
MQTT_BROKER = "192.168.0.32"
MQTT_USER = "mosquitto"
MQTT_PASSWD = "protocol-supervision-failed"


def convert_value_to_available_range(value, min_from, max_from, min_to, max_to) -> int:
    normalized = (value - min_from) / (max_from - min_from)
    new_value = min(
        round((normalized * (max_to - min_to)) + min_to),
        max_to,
    )
    return max(new_value, min_to)


def modeFromNumerical(numerical):
    # print("{:04d}".format(int(bin(mcode).replace("0b", ""))))
    mode = (numerical >> 1) % 2
    if mode == 0:
        return "color_temp"
    else:
        return "rgb"


def parseMessage(message):
    unpacked = struct.unpack(20*'B', message)

    meshid_bytes = unpacked[3]
    mode_bytes = unpacked[12]

    # these messages represent something else
    if meshid_bytes != 0 or mode_bytes > 40:
        print("Unknown message: {}".format(unpacked))
        return None, False

    # light id
    right_ID_bytes = unpacked[10]
    left_ID_bytes = unpacked[19]
    light_id = (left_ID_bytes << 8) + right_ID_bytes

    # availability
    if unpacked[11] > 0:
        availability = "online"
    else:
        availability = "offline"

    # powerstate
    if (mode_bytes % 2) > 0:
        powerstate = "ON"
    else:
        powerstate = "OFF"

    # color_mode
    color_mode = modeFromNumerical(mode_bytes)

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


def handle_mqtt_message(client, userdata, message):
    print("Got message: {} - {}".format(message.topic, message.payload))

    topic_hierarchy = message.topic.split("/")
    light_id = int(topic_hierarchy[2])

    print("Apply {} to light awox_{}".format(message.payload, light_id))


def get_name(known_lights, lid):
    if lid in known_lights.keys():
        return known_lights[lid], True
    else:
        return None, False


def get_name_from_file(filename, lid):
    with open("resp.json", "r") as file:
        devices = json.loads(file.read())
        for device in devices:
            if int(device["address"]) == int(lid):
                return device["displayName"], True
    return None, False


async def main():
    # set up light gateway
    light = awoxmeshlight_bluepy.AwoxMeshLight(
        MESH_GATEWAY, MESH_NAME, MESH_PASSWD)

    # set up mqtt client
    client = mqtt.Client()
    client.username_pw_set(MQTT_USER, MQTT_PASSWD)
    client.loop_start()

    # connect to broker
    client.connect_async(MQTT_BROKER)  # client.connect_async(MQTT_BROKER)
    print("Connected to broker.")

    # subscribe to relevant topic
    mqtt_topic = "homeassistant/light/+/set"
    client.message_callback_add(mqtt_topic, handle_mqtt_message)

    def handle_notification(characteristicHandle, data: bytearray):
        # print("{}: {}".format(characteristicHandle, data.hex()))
        message = light.decrypt_packet(data)
        state, ok = parseMessage(message)
        if ok:
            lid = state["id"]
            print("{}: ".format(lid), end="")

            base_topic = "homeassistant/light/awox_{}".format(lid)

            name, found = get_name(known_lights, lid)

            if found:
                print("{}".format(name))
            else:
                name, found = get_name_from_file("resp.json", lid)
                if found:
                    print("{}".format(name))
                else:
                    print("No light with id {} found in awox cloud data".format(lid))
                    return

                # add to known lights
                known_lights[lid] = name

                # publish config entry
                config_payload = {
                    "~": base_topic,
                    "name": "{} light".format(name),
                    "device": {
                        "hw_version": "(todo)",
                        "identifiers": [
                            "awox_{}".format(lid)
                        ],
                        "manufacturer": "AwoX",
                        "model": "(todo)",
                        "name": name,
                        "sw_version": "(todo)",
                    },
                    "unique_id": "awox_{}".format(lid),
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

                if not lid == 15148:
                    config_payload["device"]["via_device"] = "awox_{}".format(
                        15148)

                config_topic = base_topic + "/config"
                print("\tCONFIG {}".format(config_payload))
                client.publish(
                    config_topic, json.dumps(config_payload), retain=True)

            # publish light availability
            availability_topic = base_topic + "/availability"
            print("\tAVAILABILITY {}".format(state["availability"]))

            client.publish(availability_topic, json.dumps(
                state["availability"]), retain=True)

            # publish light state
            state_topic = base_topic + "/state"
            print("\tSTATE {}".format(state["state"]))
            client.publish(state_topic, json.dumps(
                state["state"]), retain=True)

            print()

    known_lights = dict()
    light.connect_with_callback(handle_notification)

    async def waitForNotifications():
        while True:
            try:
                light.btdevice.waitForNotifications(timeout=0)
            except btle.BTLEException as e:
                print(e)

    asyncio.create_task(waitForNotifications())

    await asyncio.Event().wait()


if __name__ == "__main__":
    # logging.basicConfig(level=logging.DEBUG)
    asyncio.run(main(), debug=True)
