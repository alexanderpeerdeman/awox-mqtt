import datetime
import json
import logging
import queue
import struct
from threading import Thread
from time import sleep
from typing import Optional, Tuple

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

import awoxmeshlight_bluepy
from data import Availability, ColorData, ColorMode, PowerState, StateData

# Schrank
MESH_GATEWAY = "A4:C1:38:1A:CA:39"
MESH_GATEWAY_LIGHTID = 19001

# MESH_GATEWAY = "A4:C1:38:35:D1:8C"  # Decke
# MESH_GATEWAY = "A4:C1:38:1A:3B:2C"  # Schreibtisch

MESH_NAME = "FDCqrGLE"
MESH_PASSWD = "3588b7f4"

AWOX_CLOUD_FILENAME = "resp.json"

# MQTT_BROKER = "localhost"
MQTT_BROKER = "192.168.0.32"
MQTT_USER = "mosquitto"
MQTT_PASSWD = "protocol-supervision-failed"

QUEUE_SLEEP_DURATION = datetime.timedelta(milliseconds=25)
BTDEVICE_NOTIFICATION_TIMEOUT = datetime.timedelta(milliseconds=5)
COMMAND_QUEUE_TIMEOUT = datetime.timedelta(milliseconds=1)

logger = logging.getLogger()


def convert_value_to_available_range(value, min_from, max_from, min_to, max_to) -> int:
    normalized = (value - min_from) / (max_from - min_from)
    new_value = min(
        round((normalized * (max_to - min_to)) + min_to),
        max_to,
    )
    return max(new_value, min_to)


def modeFromNumerical(numerical):
    mode = (numerical >> 1) % 2
    if mode == 0:
        return ColorMode.COLOR_TEMP
    else:
        return ColorMode.RGB


def parseMessage(message) -> Tuple[int, Optional[Availability], Optional[StateData], bool]:
    unpacked = struct.unpack(20*'B', message)

    mesh_id_bytes = unpacked[3]
    mode_bytes = unpacked[12]

    # these messages represent something else
    if mesh_id_bytes != 0 or mode_bytes > 40:
        logger.warning("Unknown message: {}".format(unpacked))
        return 0, None, None, False

    # light id
    right_id_bytes = unpacked[10]
    left_id_bytes = unpacked[19]
    light_id = int((left_id_bytes << 8) + right_id_bytes)

    # availability
    if unpacked[11] > 0:
        availability = Availability.ONLINE
    else:
        availability = Availability.OFFLINE

    # powerstate
    if (mode_bytes % 2) > 0:
        powerstate = PowerState.ON
    else:
        powerstate = PowerState.OFF

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
    if color_mode == ColorMode.RGB:
        brightness = color_brightness
    else:
        brightness = white_brightness

    # color
    red, green, blue = unpacked[16:19]

    return light_id, availability, StateData(
        brightness=brightness,
        color=ColorData(
            r=red,
            g=green,
            b=blue
        ),
        color_mode=color_mode,
        color_temp=color_temperature,
        state=powerstate,
    ), True


def get_device_from_file(light_id):
    with open(AWOX_CLOUD_FILENAME, "r", encoding='utf-8') as file:
        devices = json.loads(file.read())
        for device in devices:
            if int(device["address"]) == int(light_id):
                return device
    return None


def main():
    command_queue = queue.Queue()
    known_light_ids = dict()

    # set up light gateway
    light = awoxmeshlight_bluepy.AwoxMeshLight(
        MESH_GATEWAY, MESH_NAME, MESH_PASSWD)
    logger.info("Setup light.")

    # set up mqtt client
    mqtt_client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWD)

    def publishState(light_id: int, data: StateData):
        if data:
            mqtt_client.publish(
                "homeassistant/light/awox_{}/state".format(light_id), data.json(), retain=True)

    def publishAvailability(light_id: int, availability: Availability):
        logger.info("Publish availability for {}: {}".format(
            light_id, availability.value))
        mqtt_client.publish("homeassistant/light/awox_{}/availability".format(
            light_id), availability.value, retain=True)

    def publishConfig(light_id: int, config_payload):
        logger.info("Publish config for {}: {}".format(
            light_id, config_payload))
        mqtt_client.publish("homeassistant/light/awox_{}/config".format(light_id),
                            json.dumps(config_payload, ensure_ascii=False), retain=True)

    def handle_notification(_cHandle, data: bytearray):
        message = light.decrypt_packet(data)
        light_id, availability, state_data, ok = parseMessage(message)

        if ok:
            if not light_id in known_light_ids:
                known_light_ids[light_id] = dict()

            if not "name" in known_light_ids[light_id]:
                device = get_device_from_file(light_id)
                if device is None:
                    logger.error(
                        "No light with uid {} found in awox cloud data".format(light_id))
                    return

                # add to known lights
                name = device["displayName"]
                known_light_ids[light_id]["name"] = name

                # create config payload to publish
                config_payload = {
                    "~": "homeassistant/light/awox_{}".format(light_id),
                    # only the device name is relevant
                    "name": "",
                    "device": {
                        "hw_version": device["hardwareVersion"],
                        "identifiers": [
                            "awox_{}".format(light_id)
                        ],
                        "manufacturer": device["vendor"],
                        "model": device["modelName"],
                        "name": device["displayName"],
                        "sw_version": device["version"],
                    },
                    "unique_id": "awox_{}".format(light_id),
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

                # if we're not handling the gateway, add the via_device option to device info
                if not light_id == MESH_GATEWAY_LIGHTID:
                    config_payload["device"]["via_device"] = "awox_{}".format(
                        MESH_GATEWAY_LIGHTID)

                publishConfig(light_id, config_payload)

            known_light_ids[light_id]["availability"] = availability
            known_light_ids[light_id]["state"] = state_data

            if availability:
                publishAvailability(light_id, availability)

            if state_data:
                logger.info("(Notify) Publish state {}\t{}".format(
                    light_id, state_data))
                publishState(light_id, state_data)

    def setPowerstate(light_id, instruction: PowerState):
        if instruction == PowerState.OFF:
            command_queue.put((light.off, light_id))

        elif instruction == PowerState.ON:
            command_queue.put((light.on, light_id))

        else:
            logger.error(
                "Unknown power state intruction for {}: {}".format(light_id, instruction))
        known_light_ids[light_id]["state"].state = instruction

    def setWhiteTemperature(light_id, white_temperature_raw: int):
        white_temperature = convert_value_to_available_range(
            white_temperature_raw, 153, 500, 0, 127)

        command_queue.put((light.setWhiteTemperature,
                          white_temperature, light_id))
        known_light_ids[light_id]["state"].state = PowerState.ON
        known_light_ids[light_id]["state"].color_mode = ColorMode.COLOR_TEMP
        known_light_ids[light_id]["state"].color_temp = white_temperature_raw

    def setColor(light_id, color: ColorData):
        command_queue.put(
            (light.setColor, color.r, color.g, color.b, light_id))
        known_light_ids[light_id]["state"].state = PowerState.ON
        known_light_ids[light_id]["state"].color_mode = ColorMode.RGB
        known_light_ids[light_id]["state"].color = color

    def setBrightness(light_id, brightness_raw: int):
        if known_light_ids[light_id]["state"].color_mode == ColorMode.RGB:
            color_brightness = convert_value_to_available_range(
                brightness_raw, 3, 255, 1, 100)

            if not known_light_ids[light_id]["state"].brightness == brightness_raw:
                command_queue.put(
                    (light.setColorBrightness, color_brightness, light_id))
                known_light_ids[light_id]["state"].state = PowerState.ON
                known_light_ids[light_id]["state"].color_mode = ColorMode.RGB
                known_light_ids[light_id]["state"].brightness = brightness_raw

        elif known_light_ids[light_id]["state"].color_mode == ColorMode.COLOR_TEMP:
            white_brightness = convert_value_to_available_range(
                brightness_raw, 3, 255, 1, 127)

            if not known_light_ids[light_id]["state"].brightness == brightness_raw:
                command_queue.put(
                    (light.setWhiteBrightness, white_brightness, light_id))
                known_light_ids[light_id]["state"].state = PowerState.ON
                known_light_ids[light_id]["state"].color_mode = ColorMode.COLOR_TEMP
                known_light_ids[light_id]["state"].brightness = brightness_raw

        else:
            logger.error("Unknown color mode for {}: {}".format(
                light_id, known_light_ids[light_id]["state"].color_mode))

    light.connect_with_callback(handle_notification)

    def handle_mqtt_set_message(_client, _userdata, message):
        topic_hierarchy = message.topic.split("/")
        light_uuid = topic_hierarchy[2]
        if not str(light_uuid).startswith("awox_"):
            return

        instruction = json.loads(message.payload)
        logger.info("Set {}: {}".format(light_uuid, instruction))
        light_id = int(light_uuid[5:])  # cut away awox_ part

        if "state" in instruction.keys() and len(instruction.keys()) == 1:
            setPowerstate(light_id, PowerState(instruction["state"]))

        if "color_temp" in instruction.keys():
            color_temperature = int(instruction["color_temp"])
            setWhiteTemperature(light_id, color_temperature)

        if "color" in instruction.keys():
            color = instruction["color"]
            setColor(light_id, ColorData(color["r"], color["g"], color["b"]))

        if "brightness" in instruction.keys():
            brightness = int(instruction["brightness"])
            setBrightness(light_id, brightness)

        logger.info("(Create) Publish state {}: {}".format(
            light_id, known_light_ids[light_id]["state"]))
        publishState(light_id, known_light_ids[light_id]["state"])

    def handle_mqtt_state_message(_client, _userdata, message):
        topic_hierarchy = message.topic.split("/")
        light_uuid = topic_hierarchy[2]
        if not str(light_uuid).startswith("awox_"):
            return

        state = json.loads(message.payload)
        light_id = int(light_uuid[5:])  # cut away awox_ part

        state_data = StateData(
            brightness=state["brightness"],
            color=ColorData(
                r=state["color"]["r"],
                g=state["color"]["g"],
                b=state["color"]["b"],
            ),
            color_mode=ColorMode(state["color_mode"]),
            color_temp=state["color_temp"],
            state=PowerState(state["state"])
        )

        if not light_id in known_light_ids:
            known_light_ids[light_id] = dict()
        known_light_ids[light_id]["state"] = state_data

    def handle_mqtt_availability_message(_client, _userdata, message: mqtt.MQTTMessage):
        topic_hierarchy = message.topic.split("/")
        light_uuid = topic_hierarchy[2]
        if not str(light_uuid).startswith("awox_"):
            return

        availability = Availability(message.payload.decode())
        light_id = int(light_uuid[5:])  # cut away awox_ part

        if not light_id in known_light_ids:
            known_light_ids[light_id] = dict()
        known_light_ids[light_id]["availability"] = availability

    # connect to broker
    mqtt_client.connect(MQTT_BROKER)
    logger.info("Connected to broker.")

    def process_broker():
        mqtt_client.loop_forever()

    mqtt_client_thread = Thread(target=process_broker)
    mqtt_client_thread.start()

    mqtt_topic = "homeassistant/light/+/set"
    mqtt_client.subscribe(mqtt_topic)
    mqtt_client.message_callback_add(mqtt_topic, handle_mqtt_set_message)

    mqtt_topic = "homeassistant/light/+/state"
    mqtt_client.subscribe(mqtt_topic)
    mqtt_client.message_callback_add(mqtt_topic, handle_mqtt_state_message)

    mqtt_topic = "homeassistant/light/+/availability"
    mqtt_client.subscribe(mqtt_topic)
    mqtt_client.message_callback_add(
        mqtt_topic, handle_mqtt_availability_message)

    def process_bluetooth():
        while True:
            light.btdevice.waitForNotifications(
                timeout=BTDEVICE_NOTIFICATION_TIMEOUT.total_seconds())
            try:
                items = command_queue.get(
                    timeout=COMMAND_QUEUE_TIMEOUT.total_seconds())

            except queue.Empty:
                continue

            # unpack function and arguments from command queue and call it
            func, args = items[0], items[1:]
            func(*args)

            sleep(QUEUE_SLEEP_DURATION.total_seconds())

    bluetooth_thread = Thread(target=process_bluetooth)
    bluetooth_thread.start()

    mqtt_client_thread.join()
    bluetooth_thread.join()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()
