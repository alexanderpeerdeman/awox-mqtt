
import asyncio
import logging

import paho.mqtt.client as mqtt

from lightmanager import LightManager

# TODO: Handle restart of broker gracefully
# TODO: Check that retained messages are correct (state, availability, config)
# TODO: Name devices by querying AwoX Cloud.
# BUG: When HAss restarts, the lights are set to something.


# MQTT_BROKER = "192.168.0.32"
MQTT_BROKER = "localhost"
MQTT_USER = "mosquitto"
MQTT_PASSWD = "protocol-supervision-failed"


def handle_set_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
    print("GOT {}: {}".format(msg.topic, msg.payload))
    topic_levels = msg.topic.split("/")
    target_light = int(topic_levels[2])

    if topic_levels[3] == "set":
        lightmanager.apply_state(target_light, msg.payload)


def handle_status_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
    print("HAss Status Update: {}", format(msg.payload))
    if msg.payload == "online":
        pass


def on_connect(client: mqtt.Client, userdata, flags, rc):
    topic = "homeassistant/light/+/set"
    client.subscribe(topic)
    client.message_callback_add(topic, handle_set_message)

    topic = "homeassistant/status"
    client.subscribe(topic)
    client.message_callback_add(topic, handle_status_message)


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
    print("No filter matched. Topic: {}, Message: {}".format(msg.topic, msg.payload))


def main():
    global lightmanager

    mqtt_client = mqtt.Client()
    mqtt_client.loop_start()

    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWD)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    mqtt_client.connect(MQTT_BROKER)
    print("Connected to broker.")

    lightManager = LightManager(mqtt_client)

    print("LightManager created.")

    asyncio.Event().wait()


logging.basicConfig(level=logging.DEBUG)
asyncio.run(main(), debug=True)


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
