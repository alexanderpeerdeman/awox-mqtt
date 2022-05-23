import struct
import time
import awoxmeshlight
from awoxmeshlight import packetutils as pckt
import logging
import webcolors


def closest_color(requested_color):
    min_colors = {}
    for key, name in webcolors.CSS3_HEX_TO_NAMES.items():
        r_c, g_c, b_c = webcolors.hex_to_rgb(key)
        rd = (r_c - requested_color[0]) ** 2
        gd = (g_c - requested_color[1]) ** 2
        bd = (b_c - requested_color[2]) ** 2
        min_colors[(rd + gd + bd)] = name
    return min_colors[min(min_colors.keys())]

def get_color_name(requested_color):
    try:
        closest_name = actual_name = webcolors.rgb_to_name(requested_color)
    except ValueError:
        closest_name = closest_color(requested_color)
        actual_name = None
    return actual_name, closest_name

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
        logger.info("Received message : %s", repr(message))
        self.light.parseStatusResult(message)


def myParseStatusResult(self, message):
    meshid = struct.unpack('B', message[3:4])[0]
    for i, m in enumerate(struct.unpack('B'*20, message)):
        print("{:03d} ".format(m), end="")
    print("")
    idR = struct.unpack('B', message[10:11])[0]
    idL = struct.unpack('B', message[19:20])[0]

    integer_meshid = (idL << 8) + idR

    print("meshid:", integer_meshid)
    mode = struct.unpack('B', message[12:13])[0]

    if mode < 40 and meshid == 0:  # filter some messages that return something else
        # mode 1 = white
        # mode 5 = white
        # mode 3 = color
        # mode 7 = transition
        self.mode = mode
        print(self.mode)
        self.status = mode % 2
        print(self.status)

        self.white_brightness, self.white_temp = struct.unpack(
            'BB', message[13:15])
        print(self.white_brightness, self.white_temp)

        self.color_brightness, self.red, self.green, self.blue = struct.unpack(
            'BBBB', message[15:19])
        print(self.color_brightness, self.red, self.green, self.blue)
        _, closest_name = get_color_name([self.red, self.green, self.blue])
        print("Brightness: {}, Color: {}".format(self.color_brightness, closest_name))


logger = logging.getLogger("awoxmeshlight")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)

MESH_NAME = "FDCqrGLE"
MESH_PASSWORD = "3588b7f4"

light = awoxmeshlight.AwoxMeshLight(
    "a4:c1:38:35:d1:8c", MESH_NAME, MESH_PASSWORD)


light.parseStatusResult = type(
    light.parseStatusResult)(myParseStatusResult, light)
light.btdevice.delegate.handleNotification = type(
    light.btdevice.delegate.handleNotification)(myHandleNotification, light)


light.connect()

while True:
    if light.btdevice.waitForNotifications(1.0):
        continue
    time.sleep(0.25)
