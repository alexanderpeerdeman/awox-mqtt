import asyncio
from email import charset
import logging
import awoxmeshlight_bleak

MESH_GATEWAY = "a4:c1:38:1a:3b:2c"  # Schreibtisch
MESH_NAME = "FDCqrGLE"
MESH_PASSWD = "3588b7f4"


def callback(sender: int, data: bytearray):
    print(f"{sender}: {data}")


async def main():
    light = awoxmeshlight_bleak.AwoxMeshLight(
        MESH_GATEWAY, MESH_NAME, MESH_PASSWD)
    print(light)

    await light.connect()
    # for service in light.btdevice.services:
    #     for char in service.characteristics:
    #         print(char)
    #         print(await light.btdevice.read_gatt_char(char))

    # print(await light.btdevice.read_gatt_char())

    print("fw", await light.getFirmwareRevision())
    print("hw", await light.getHardwareRevision())
    print("mn", await light.getModelNumber())

    await light.off()
    await asyncio.sleep(1)
    await light.on()

    await light.btdevice.start_notify(awoxmeshlight_bleak.STATUS_CHAR_UUID, callback)
    await asyncio.sleep(20)

    await light.disconnect()


# logging.basicConfig(level=logging.DEBUG)
asyncio.run(main())
