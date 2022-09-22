#!/bin/bash

mosquitto_pub -h 192.168.0.32 -u mosquitto -P protocol-supervision-failed -t homeassistant/light/8841/config -n
mosquitto_pub -h 192.168.0.32 -u mosquitto -P protocol-supervision-failed -t homeassistant/light/19001/config -n
mosquitto_pub -h 192.168.0.32 -u mosquitto -P protocol-supervision-failed -t homeassistant/light/15148/config -n
mosquitto_pub -h 192.168.0.32 -u mosquitto -P protocol-supervision-failed -t homeassistant/light/19289/config -n
mosquitto_pub -h 192.168.0.32 -u mosquitto -P protocol-supervision-failed -t homeassistant/light/20876/config -n
mosquitto_pub -h 192.168.0.32 -u mosquitto -P protocol-supervision-failed -t homeassistant/light/2/config -n