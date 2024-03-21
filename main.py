from ast import parse
import json
import logging
from multiprocessing import Process
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
MESH_GATEWAY_LID = 19001

# MESH_GATEWAY = "A4:C1:38:35:D1:8C"  # Decke
# MESH_GATEWAY = "A4:C1:38:1A:3B:2C"  # Schreibtisch

MESH_NAME = "FDCqrGLE"
MESH_PASSWD = "3588b7f4"

AWOX_CLOUD_FILENAME = "resp.json"

# MQTT_BROKER = "localhost"
MQTT_BROKER = "192.168.0.32"
MQTT_USER = "mosquitto"
MQTT_PASSWD = "protocol-supervision-failed"

QUEUE_SLEEP = 0.025

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

    meshid_bytes = unpacked[3]
    mode_bytes = unpacked[12]

    # these messages represent something else
    if meshid_bytes != 0 or mode_bytes > 40:
        logger.warning("Unknown message: {}".format(unpacked))
        return 0, None, None, False

    # light id
    right_ID_bytes = unpacked[10]
    left_ID_bytes = unpacked[19]
    light_id = int((left_ID_bytes << 8) + right_ID_bytes)

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


def get_device_from_file(lid):
    with open(AWOX_CLOUD_FILENAME, "r", encoding='utf-8') as file:
        devices = json.loads(file.read())
        for device in devices:
            if int(device["address"]) == int(lid):
                return device
    return None


def main():
    command_queue = queue.Queue()
    known_lights = dict()

    # set up light gateway
    light = awoxmeshlight_bluepy.AwoxMeshLight(
        MESH_GATEWAY, MESH_NAME, MESH_PASSWD)
    logger.info("Setup light.")

    # set up mqtt client
    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASSWD)

    def publishState(lid: int, data: Optional[StateData]):
        if data:
            client.publish(
                "homeassistant/light/awox_{}/state".format(lid), data.json(), retain=True)

    def publishAvailability(lid: int, availability: Availability):
        client.publish("homeassistant/light/awox_{}/availability".format(
            lid), availability.value, retain=True)

    def publishConfig(lid: int, config_payload):
        logger.info("Publish config: {}".format(lid))
        client.publish("homeassistant/light/awox_{}/config".format(lid),
                       json.dumps(config_payload), retain=True)

    def handle_notification(_, data: bytearray):
        message = light.decrypt_packet(data)
        lid, availability, parsed_state_data, ok = parseMessage(message)

        if ok:
            if not lid in known_lights:
                known_lights[lid] = dict()

            if not "name" in known_lights[lid]:
                device = get_device_from_file(lid)
                if device is None:
                    logger.error(
                        "No light with uid {} found in awox cloud data".format(lid))
                    return

                # add to known lights
                name = device["displayName"]
                known_lights[lid]["name"] = name

                # publish config entry
                config_payload = {
                    "~": "homeassistant/light/awox_{}".format(lid),
                    "name": "{}".format(device["displayName"]),
                    "device": {
                        "hw_version": device["hardwareVersion"],
                        "identifiers": [
                            "awox_{}".format(lid)
                        ],
                        "manufacturer": device["vendor"],
                        "model": device["modelName"],
                        "name": device["displayName"],
                        "sw_version": device["version"],
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

                # if we're not handling the gateway, add the via_device option to device info
                if not lid == MESH_GATEWAY_LID:
                    config_payload["device"]["via_device"] = "awox_{}".format(
                        MESH_GATEWAY_LID)

                publishConfig(lid, config_payload)

            known_lights[lid]["availability"] = availability
            known_lights[lid]["state"] = parsed_state_data

            if not "availabilityProcess" in known_lights[lid]:
                known_lights[lid]["availabilityProcess"] = None

            def _schedule_worker(seconds, lid, availability):
                sleep(seconds)
                publishAvailability(lid, availability)

            # publish light availability
            if availability == Availability.OFFLINE:
                process = known_lights[lid]["availabilityProcess"]
                if not isinstance(process, Process):
                    seconds = 20
                    logger.info("Got {}: OFFLINE. Scheduling offline message to be published in {} seconds.".format(
                        lid, seconds))
                    known_lights[lid]["availabilityProcess"] = Process(
                        target=_schedule_worker, args=(seconds, lid, availability))
                    known_lights[lid]["availabilityProcess"].start()
            if availability == Availability.ONLINE:
                process = known_lights[lid]["availabilityProcess"]
                if isinstance(process, Process) and process.is_alive():
                    logger.info(
                        "Light {} came back online again. Cancelling publish".format(lid))
                    process.kill()
                    known_lights[lid]["availabilityProcess"] = None
                else:
                    publishAvailability(lid, availability)

            # publish light state
            logger.info("(Notify) Publish state {}\t{}".format(
                lid, parsed_state_data))
            publishState(lid, parsed_state_data)

    def setPowerstate(lid, instruction: PowerState):
        if instruction == PowerState.OFF:
            command_queue.put((light.off, lid))

        elif instruction == PowerState.ON:
            command_queue.put((light.on, lid))

        else:
            logger.error(
                "Unknown power state intruction for {}: {}".format(lid, instruction))
        known_lights[lid]["state"].state = instruction

    def setWhiteTemperature(lid, instruction: int):
        adjusted = convert_value_to_available_range(
            instruction, 153, 500, 0, 127)

        command_queue.put((light.setWhiteTemperature, adjusted, lid))
        known_lights[lid]["state"].state = PowerState.ON
        known_lights[lid]["state"].color_mode = ColorMode.COLOR_TEMP
        known_lights[lid]["state"].color_temp = instruction

    def setColor(lid, col: ColorData):
        command_queue.put((light.setColor, col.r, col.g, col.b, lid))
        known_lights[lid]["state"].state = PowerState.ON
        known_lights[lid]["state"].color_mode = ColorMode.RGB
        known_lights[lid]["state"].color = col

    def setBrightness(lid, instruction: int):
        if known_lights[lid]["state"].color_mode == ColorMode.RGB:
            adjusted = convert_value_to_available_range(
                instruction, 3, 255, 1, 100)

            if not known_lights[lid]["state"].brightness == instruction:
                command_queue.put((light.setColorBrightness, adjusted, lid))
                known_lights[lid]["state"].state = PowerState.ON
                known_lights[lid]["state"].color_mode = ColorMode.RGB
                known_lights[lid]["state"].brightness = instruction

        elif known_lights[lid]["state"].color_mode == ColorMode.COLOR_TEMP:
            adjusted = convert_value_to_available_range(
                instruction, 3, 255, 1, 127)

            if not known_lights[lid]["state"].brightness == instruction:
                command_queue.put((light.setWhiteBrightness, adjusted, lid))
                known_lights[lid]["state"].state = PowerState.ON
                known_lights[lid]["state"].color_mode = ColorMode.COLOR_TEMP
                known_lights[lid]["state"].brightness = instruction

        else:
            logger.error("Unknown color mode for {}: {}".format(
                lid, known_lights[lid]["state"].color_mode))

    light.connect_with_callback(handle_notification)

    def handle_mqtt_set_message(client, userdata, message):
        topic_hierarchy = message.topic.split("/")
        light_uuid = topic_hierarchy[2]
        if not str(light_uuid).startswith("awox_"):
            return

        instruction = json.loads(message.payload)
        logger.info("Set {}: {}".format(light_uuid, instruction))
        lid = int(light_uuid[5:])  # cut away awox_ part

        if "state" in instruction.keys() and len(instruction.keys()) == 1:
            setPowerstate(lid, PowerState(instruction["state"]))

        if "color_temp" in instruction.keys():
            setWhiteTemperature(lid, int(instruction["color_temp"]))

        if "color" in instruction.keys():
            col = instruction["color"]
            setColor(lid, ColorData(col["r"], col["g"], col["b"]))

        if "brightness" in instruction.keys():
            setBrightness(lid, int(instruction["brightness"]))

        logger.info("(Create) Publish state {}\t{}".format(
            lid, known_lights[lid]["state"]))
        publishState(lid, known_lights[lid]["state"])

    def handle_mqtt_state_message(client, userdata, message):
        topic_hierarchy = message.topic.split("/")
        light_uuid = topic_hierarchy[2]
        if not str(light_uuid).startswith("awox_"):
            return

        state = json.loads(message.payload)
        lid = int(light_uuid[5:])  # cut away awox_ part

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

        if not lid in known_lights:
            known_lights[lid] = dict()
        known_lights[lid]["state"] = state_data

    def handle_mqtt_availability_message(client, userdata, message: mqtt.MQTTMessage):
        topic_hierarchy = message.topic.split("/")
        light_uuid = topic_hierarchy[2]
        if not str(light_uuid).startswith("awox_"):
            return

        availability = Availability(message.payload.decode())
        lid = int(light_uuid[5:])  # cut away awox_ part

        if not lid in known_lights:
            known_lights[lid] = dict()
        known_lights[lid]["availability"] = availability

    # connect to broker
    client.connect(MQTT_BROKER)
    logger.info("Connected to broker.")

    def process_broker():
        client.loop_forever()

    broker_thread = Thread(target=process_broker)
    broker_thread.start()

    mqtt_topic = "homeassistant/light/+/set"
    client.subscribe(mqtt_topic)
    client.message_callback_add(mqtt_topic, handle_mqtt_set_message)

    mqtt_topic = "homeassistant/light/+/state"
    client.subscribe(mqtt_topic)
    client.message_callback_add(mqtt_topic, handle_mqtt_state_message)

    mqtt_topic = "homeassistant/light/+/availability"
    client.subscribe(mqtt_topic)
    client.message_callback_add(mqtt_topic, handle_mqtt_availability_message)

    def process_bluetooth():
        while True:
            light.btdevice.waitForNotifications(timeout=0.05)
            try:
                items = command_queue.get(timeout=0.01)

            except queue.Empty:
                continue

            func = items[0]
            args = items[1:]

            func(*args)
            sleep(QUEUE_SLEEP)

    bluetooth_thread = Thread(target=process_bluetooth)
    bluetooth_thread.start()

    broker_thread.join()
    bluetooth_thread.join()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    main()
