# Control AwoX Smart Lights through MQTT (Homeassistant)

This project allows to join the AwoX smart lights Bluetooth LE Mesh and control them with Homeassistant through an MQTT-Broker.

## Instructions

1. Use `awoxconnect.py` to request the appropriate Bluetooth Mesh credentials from AwoX cloud

2. Setup environment file:  
   Rename `secrets.env` to `.env`

3. Select which light should be used as a gateway

4. Then run `python main.py`

---

Insprired in large parts by [fsaris/home-assistant-awox](https://github.com/fsaris/home-assistant-awox)
