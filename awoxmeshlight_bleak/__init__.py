
from bleak import BleakClient
from . import packetutils as pckt

from os import urandom
import logging
import struct

# Commands :

#: Set mesh groups.
#: Data : 3 bytes
C_MESH_GROUP = 0xd7

#: Set the mesh id. The light will still answer to the 0 mesh id. Calling the
#: command again replaces the previous mesh id.
#: Data : the new mesh id, 2 bytes in little endian order
C_MESH_ADDRESS = 0xe0

#:
C_MESH_RESET = 0xe3

#: On/Off command. Data : one byte 0, 1
C_POWER = 0xd0

#: Data : one byte
C_LIGHT_MODE = 0x33

#: Data : one byte 0 to 6
C_PRESET = 0xc8

#: White temperature. one byte 0 to 0x7f
C_WHITE_TEMPERATURE = 0xf0

#: one byte 1 to 0x7f
C_WHITE_BRIGHTNESS = 0xf1

#: 4 bytes : 0x4 red green blue
C_COLOR = 0xe2

#: one byte : 0xa to 0x64 ....
C_COLOR_BRIGHTNESS = 0xf2

#: Data 4 bytes : How long a color is displayed in a sequence in milliseconds as
#:   an integer in little endian order
C_SEQUENCE_COLOR_DURATION = 0xf5

#: Data 4 bytes : Duration of the fading between colors in a sequence, in
#:   milliseconds, as an integer in little endian order
C_SEQUENCE_FADE_DURATION = 0xf6

#: 7 bytes
C_TIME = 0xe4

#: 10 bytes
C_ALARMS = 0xe5


PAIR_CHAR_UUID = '00010203-0405-0607-0809-0a0b0c0d1914'
COMMAND_CHAR_UUID = '00010203-0405-0607-0809-0a0b0c0d1912'
STATUS_CHAR_UUID = '00010203-0405-0607-0809-0a0b0c0d1911'
OTA_CHAR_UUID = '00010203-0405-0607-0809-0a0b0c0d1913'


logger = logging.getLogger(__name__)


# class Delegate(btle.DefaultDelegate):
#     def __init__(self, light):
#         self.light = light
#         btle.DefaultDelegate.__init__(self)

#     def handleNotification(self, cHandle, data):
#         char = self.light.btdevice.getCharacteristics(cHandle)[0]
#         if char.uuid == STATUS_CHAR_UUID:
#             logger.info("Notification on status char.")
#             message = pckt.decrypt_packet(
#                 self.light.session_key, self.light.mac, data)
#         else:
#             logger.info("Receiced notification from characteristic %s",
#                         char.uuid.getCommonName())
#             message = pckt.decrypt_packet(
#                 self.light.session_key, self.light.mac, data)
#             logger.info("Received message : %s", repr(message))
#             self.light.parseStatusResult(message)


class AwoxMeshLight:
    def __init__(self, mac, mesh_name="unpaired", mesh_password="1234"):
        """
        Args :
            mac: The light's MAC address as a string in the form AA:BB:CC:DD:EE:FF
            mesh_name: The mesh name as a string.
            mesh_password: The mesh password as a string.
        """
        self.mac = mac
        self.mesh_id = 0
        self.btdevice: BleakClient = None
        self.session_key = None
        self.command_char = None
        self.mesh_name = mesh_name.encode()
        self.mesh_password = mesh_password.encode()

        # Light status
        self.white_brightness = None
        self.white_temp = None
        self.color_brightness = None
        self.red = None
        self.green = None
        self.blue = None
        self.mode = None
        self.status = None

    async def connect(self, mesh_name=None, mesh_password=None):
        """
        Args :
            mesh_name: The mesh name as a string.
            mesh_password: The mesh password as a string.
        """
        if mesh_name:
            self.mesh_name = mesh_name.encode()
        if mesh_password:
            self.mesh_password = mesh_password.encode()

        assert len(self.mesh_name) <= 16, "mesh_name can hold max 16 bytes"
        assert len(
            self.mesh_password) <= 16, "mesh_password can hold max 16 bytes"

        self.btdevice = BleakClient(self.mac)

        await self.btdevice.connect()
        # self.btdevice.setDelegate(Delegate(self))

        pair_char = self.btdevice.services.get_characteristic(
            specifier=PAIR_CHAR_UUID)
        self.session_random = urandom(8)

        message = pckt.make_pair_packet(
            self.mesh_name, self.mesh_password, self.session_random)
        await self.btdevice.write_gatt_char(pair_char, message)

        status_char = self.btdevice.services.get_characteristic(
            specifier=STATUS_CHAR_UUID)
        await self.btdevice.write_gatt_char(status_char, b'\x01')

        reply = await self.btdevice.read_gatt_char(pair_char)
        if reply[0] == 0xd:
            self.session_key = pckt.make_session_key(self.mesh_name, self.mesh_password,
                                                     self.session_random, reply[1:9])
            print("Connected.")
            logger.info("Connected.")
            return True
        else:
            if reply[0] == 0xe:
                logger.info("Auth error : check name and password.")
                print("Auth error : check name and password.")
            else:
                logger.info("Unexpected pair value : %s", repr(reply))
                print("Unexpected pair value : %s", repr(reply))
            await self.disconnect()
            return False

    async def writeCommand(self, command, data, dest=None):
        """
        Args:
            command: The command, as a number.
            data: The parameters for the command, as bytes.
            dest: The destination mesh id, as a number. If None, this lightbulb's
                mesh id will be used.
        """
        assert (self.session_key)
        if dest == None:
            dest = self.mesh_id
        packet = pckt.make_command_packet(
            self.session_key, self.mac, dest, command, data)

        if not self.command_char:
            self.command_char = self.btdevice.services.get_characteristic(
                specifier=COMMAND_CHAR_UUID)

        try:
            logger.info("[%s] Writing command %i data %s",
                        self.mac, command, repr(data))
            await self.btdevice.write_gatt_char(self.command_char, packet)
        except:
            logger.info('[%s] (Re)load characteristics', self.mac)
            self.command_char = self.btdevice.services.get_characteristic(
                specifier=COMMAND_CHAR_UUID)
            logger.info("[%s] Writing command %i data %s",
                        self.mac, command, repr(data))
            await self.btdevice.write_gatt_char(self.command_char, packet)

    async def readStatus(self):
        status_char = self.btdevice.services.get_characteristic(
            specifier=STATUS_CHAR_UUID)
        packet = await self.btdevice.read_gatt_char(status_char)
        return pckt.decrypt_packet(self.session_key, self.mac, packet)

    async def setColor(self, red, green, blue):
        """
        Args :
            red, green, blue: between 0 and 0xff
        """
        data = struct.pack('BBBB', 0x04, red, green, blue)
        await self.writeCommand(C_COLOR, data)

    async def setColorBrightness(self, brightness):
        """
        Args :
            brightness: a value between 0xa and 0x64 ...
        """
        data = struct.pack('B', brightness)
        await self.writeCommand(C_COLOR_BRIGHTNESS, data)

    async def setSequenceColorDuration(self, duration):
        """
        Args :
            duration: in milliseconds.
        """
        data = struct.pack("<I", duration)
        await self.writeCommand(C_SEQUENCE_COLOR_DURATION, data)

    async def setSequenceFadeDuration(self, duration):
        """
        Args:
            duration: in milliseconds.
        """
        data = struct.pack("<I", duration)
        await self.writeCommand(C_SEQUENCE_FADE_DURATION, data)

    async def setPreset(self, num):
        """
        Set a preset color sequence.

        Args :
            num: number between 0 and 6
        """
        data = struct.pack('B', num)
        await self.writeCommand(C_PRESET, data)

    async def setWhiteBrightness(self, brightness):
        """
        Args :
            brightness: between 1 and 0x7f
        """
        data = struct.pack('B', brightness)
        await self.writeCommand(C_WHITE_BRIGHTNESS, data)

    async def setWhiteTemperature(self, brightness):
        """
        Args :
            temp: between 0 and 0x7f
        """
        data = struct.pack('B', brightness)
        await self.writeCommand(C_WHITE_TEMPERATURE, data)

    async def setWhite(self, temp, brightness):
        """
        Args :
            temp: between 0 and 0x7f
            brightness: between 1 and 0x7f
        """
        data = struct.pack('B', temp)
        await self.writeCommand(C_WHITE_TEMPERATURE, data)
        data = struct.pack('B', brightness)
        await self.writeCommand(C_WHITE_BRIGHTNESS, data)

    async def on(self):
        """ Turns the light on.
        """
        await self.writeCommand(C_POWER, b'\x01')

    async def off(self):
        """ Turns the light off.
        """
        await self.writeCommand(C_POWER, b'\x00')

    async def disconnect(self):
        logger.info("Disconnecting.")
        print("Disconnecting.")

        await self.btdevice.disconnect()
        self.session_key = None

    def getFirmwareRevision(self):
        """
        Returns :
            The firmware version as a null terminated utf-8 string.
        """
        return self.btdevice.read_gatt_char(char_specifier="00002a26-0000-1000-8000-00805f9b34fb")

    def getHardwareRevision(self):
        """
        Returns :
            The hardware version as a null terminated utf-8 string.
        """
        return self.btdevice.read_gatt_char(char_specifier="00002a27-0000-1000-8000-00805f9b34fb")

    def getModelNumber(self):
        """
        Returns :
            The model as a null terminated utf-8 string.
        """
        return self.btdevice.read_gatt_char(char_specifier="00002a24-0000-1000-8000-00805f9b34fb")
