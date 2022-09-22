import json
import struct
import typing
from time import sleep

import awoxmeshlight
import paho.mqtt.client as mqtt
from awoxmeshlight import packetutils as pckt
from bluepy import btle

from awoxsmartlight import AwoXSmartLight

# TODO: Handle restart of broker gracefully
# TODO: Check that retained messages are correct (state, availability, config)
# TODO: Name devices by querying AwoX Cloud.
# BUG: When HAss restarts, the lights are set to something.

MESH_GATEWAY = "a4:c1:38:1a:ca:39"
MESH_NAME = "FDCqrGLE"
MESH_PASSWD = "3588b7f4"

MQTT_BROKER = "192.168.0.32"
MQTT_USER = "mosquitto"
MQTT_PASSWD = "protocol-supervision-failed"


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
    def __init__(self, _gateway: awoxmeshlight.AwoxMeshLight, _lights: typing.Mapping[int, AwoXSmartLight]):
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
            new_light = AwoXSmartLight(light_id, self.gateway, mqtt_client)
            self.known_lights[light_id] = new_light
            new_light.setState(state, force_publish=True)
        else:
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

# Was sich Valentin überlegt hat.
# MQTT_BROKER = "192.168.0.32"
# MQTT_USER = "mosquitto"
# MQTT_PASSWD = "protocol-supervision-failed"

# logging.basicConfig(level=logging.INFO)

# logging.info("Starting up")


# mon = co2.CO2monitor()


# def on_connect(client, userdata, flags, rc):
#     if rc == 0:
#         client.is_connected = True
#         logging.info("Connected to broker")
#     else:
#         logging.info("Connect failed")


# def on_disconnect(client, userdata, rc):
#     client.is_connected = False
#     logging.info("Disconnected from broker")


# client = mqtt.Client()
# client.on_connect = on_connect
# client.on_disconnect = on_disconnect
# client.username_pw_set(MQTT_USER, MQTT_PASSWD)
# client.loop_start()
# client.connect(MQTT_BROKER, 1883, 60)


# while True:
#     data = mon.read_data()

#     json_data = {
#         "time": data[0].strftime("%Y-%m-%d %H:%M:%S"),
#         "co2": data[1],
#         "temp": data[2],
#         "hum": data[3]
#     }

#     if not client.is_connected:
#         time.sleep(10)
#         logging.info("trying to reconnect")
#         client.reconnect()

#     client.publish("valentin/co2-sensor/co2", data[1])
#     client.publish("valentin/co2-sensor/temp", data[2])
#     client.publish("valentin/co2-sensor/hum", data[3])

#     logging.info("Published")
#     time.sleep(10)
