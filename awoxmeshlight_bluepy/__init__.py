import logging
import struct
from os import urandom
from typing import Any, Callable

from bluepy import btle

from . import packetutils as pckt

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
        self.btdevice = btle.Peripheral()
        self.session_key = None
        self.command_char = None
        self.mesh_name = mesh_name.encode()
        self.mesh_password = mesh_password.encode()

    def connect_with_callback(self, callback: Callable, mesh_name=None, mesh_password=None):
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

        class DelegateNotification(btle.DefaultDelegate):
            def __init__(self):
                btle.DefaultDelegate.__init__(self)

            def handleNotification(self, cHandle, data):
                callback(cHandle, data)

        self.btdevice.connect(self.mac)
        self.btdevice.setDelegate(DelegateNotification())

        # send pair message
        pair_char = self.btdevice.getCharacteristics(uuid=PAIR_CHAR_UUID)[0]
        self.session_random = urandom(8)
        message = pckt.make_pair_packet(
            self.mesh_name, self.mesh_password, self.session_random)
        pair_char.write(message)

        # get status (?)
        status_char = self.btdevice.getCharacteristics(
            uuid=STATUS_CHAR_UUID)[0]
        status_char.write(b'\x01')

        # read pairing reply
        reply = bytearray(pair_char.read())
        if reply[0] == 0xd:
            self.session_key = pckt.make_session_key(self.mesh_name, self.mesh_password,
                                                     self.session_random, reply[1:9])
            logger.info("Connected.")
            return True
        else:
            if reply[0] == 0xe:
                logger.info("Auth error : check name and password.")
            else:
                logger.info("Unexpected pair value : %s", repr(reply))
            self.disconnect()
            return False

    def writeCommand(self, command, data, dest=None):
        """
        Args:
            command: The command, as a number.
            data: The parameters for the command, as bytes.
            dest: The destination mesh id, as a number. If None, this lightbulb's mesh id will be used.
        """
        assert (self.session_key)
        if dest == None:
            dest = self.mesh_id
        packet = pckt.make_command_packet(
            self.session_key, self.mac, dest, command, data)

        if not self.command_char:
            self.command_char = self.btdevice.getCharacteristics(uuid=COMMAND_CHAR_UUID)[
                0]

        try:
            logger.info("[%s] Writing command %i data %s",
                        self.mac, command, repr(data))
            self.command_char.write(packet)
        except:
            logger.info('[%s] (Re)load characteristics', self.mac)
            self.command_char = self.btdevice.getCharacteristics(uuid=COMMAND_CHAR_UUID)[
                0]
            logger.info("[%s] Writing command %i data %s",
                        self.mac, command, repr(data))
            self.command_char.write(packet)

    def readStatus(self):
        status_char = self.btdevice.getCharacteristics(
            uuid=STATUS_CHAR_UUID)[0]
        packet = status_char.read()
        return pckt.decrypt_packet(self.session_key, self.mac, packet)

    def decrypt_packet(self, packet):
        return pckt.decrypt_packet(self.session_key, self.mac, packet)

    def setColor(self, red, green, blue, dest=None):
        """
        Args :
            red, green, blue: between 0 and 0xff
        """
        data = struct.pack('BBBB', 0x04, red, green, blue)
        self.writeCommand(C_COLOR, data, dest)

    def setColorBrightness(self, brightness, dest=None):
        """
        Args :
            brightness: a value between 0xa and 0x64 ...
        """
        data = struct.pack('B', brightness)
        self.writeCommand(C_COLOR_BRIGHTNESS, data, dest)

    def setSequenceColorDuration(self, duration, dest=None):
        """
        Args :
            duration: in milliseconds.
        """
        data = struct.pack("<I", duration)
        self.writeCommand(C_SEQUENCE_COLOR_DURATION, data, dest)

    def setSequenceFadeDuration(self, duration, dest=None):
        """
        Args:
            duration: in milliseconds.
        """
        data = struct.pack("<I", duration)
        self.writeCommand(C_SEQUENCE_FADE_DURATION, data, dest)

    def setPreset(self, num, dest=None):
        """
        Set a preset color sequence.

        Args :
            num: number between 0 and 6
        """
        data = struct.pack('B', num)
        self.writeCommand(C_PRESET, data, dest)

    def setWhiteBrightness(self, brightness, dest=None):
        """
        Args :
            brightness: between 1 and 0x7f
        """
        data = struct.pack('B', brightness)
        self.writeCommand(C_WHITE_BRIGHTNESS, data, dest)

    def setWhiteTemperature(self, brightness, dest=None):
        """
        Args :
            temp: between 0 and 0x7f
        """
        data = struct.pack('B', brightness)
        self.writeCommand(C_WHITE_TEMPERATURE, data, dest)

    def setWhite(self, temp, brightness, dest=None):
        """
        Args :
            temp: between 0 and 0x7f
            brightness: between 1 and 0x7f
        """
        data = struct.pack('B', temp)
        self.writeCommand(C_WHITE_TEMPERATURE, data, dest)
        data = struct.pack('B', brightness)
        self.writeCommand(C_WHITE_BRIGHTNESS, data, dest)

    def on(self, dest=None):
        """ Turns the light on.
        """
        self.writeCommand(C_POWER, b'\x01', dest)

    def off(self, dest=None):
        """ Turns the light off.
        """
        self.writeCommand(C_POWER, b'\x00', dest)

    def disconnect(self):
        logger.info("Disconnecting.")
        self.btdevice.disconnect()
        self.session_key = None

    def getFirmwareRevision(self):
        """
        Returns :
            The firmware version as a null terminated utf-8 string.
        """
        char = self.btdevice.getCharacteristics(
            uuid=btle.AssignedNumbers.firmwareRevisionString)[0]
        return char.read()

    def getHardwareRevision(self):
        """
        Returns :
            The hardware version as a null terminated utf-8 string.
        """
        char = self.btdevice.getCharacteristics(
            uuid=btle.AssignedNumbers.hardwareRevisionString)[0]
        return char.read()

    def getModelNumber(self):
        """
        Returns :
            The model as a null terminated utf-8 string.
        """
        char = self.btdevice.getCharacteristics(
            uuid=btle.AssignedNumbers.modelNumberString)[0]
        return char.read()
