"""Parser for KBeacon (KBPro) BLE advertisements."""

from __future__ import annotations

import logging
import struct

from bluetooth_data_tools import short_address
from bluetooth_sensor_state_data import BluetoothData
from habluetooth import BluetoothServiceInfoBleak
from sensor_state_data import SensorLibrary

_LOGGER = logging.getLogger(__name__)

# FEAA is the Eddystone UUID
FEAA_UUID = "0000feaa-0000-1000-8000-00805f9b34fb"
KB_EXT_UUID = "00002080-0000-1000-8000-00805f9b34fb"

FRAME_TYPE_UID = 0x00
FRAME_TYPE_URL = 0x10
FRAME_TYPE_TLM = 0x20
FRAME_TYPE_SENSOR = 0x21
FRAME_TYPE_SYSTEM = 0x22

# Sensor mask bits
MASK_VOLTAGE = 1 << 0  # bit 0: Voltage (2 bytes, mV)
MASK_TEMPERATURE = 1 << 1  # bit 1: Temperature (2 bytes, signed 8.8 fixed point)
MASK_HUMIDITY = 1 << 2  # bit 2: Humidity (2 bytes, 8.8 fixed point)
MASK_ACC = 1 << 3  # bit 3: Accelerometer X,Y,Z (3*2 bytes, mg)
MASK_CUTOFF = 1 << 4  # bit 4: Cutoff status (1 byte)
MASK_PIR = 1 << 5  # bit 5: PIR indication (1 byte)
MASK_LUX = 1 << 6  # bit 6: Light (2 bytes)
MASK_VOC = 1 << 7  # bit 7: VOC (1 + 2 + 2 bytes)
MASK_CO2 = 1 << 9  # bit 9: CO2
MASK_UNREAD_RECORDS = 1 << 10  # bit 10: Unread record count (1 + 2 bytes)

# Cached struct unpackers for efficiency
_UNPACK_U16_BE = struct.Struct(">H").unpack
_UNPACK_S16_BE = struct.Struct(">h").unpack


class KBeaconBluetoothDeviceData(BluetoothData):
    """Data parser for KBeacon (KBPro) Bluetooth devices."""

    def _start_update(self, service_info: BluetoothServiceInfoBleak) -> None:
        """Update from BLE advertisement data."""
        _LOGGER.debug("Parsing KBeacon BLE advertisement data: %s", service_info)

        service_data = self._service_data_by_uuid(service_info)
        feaa_data = service_data.get(FEAA_UUID)
        kb_ext_data = service_data.get(KB_EXT_UUID)

        if not feaa_data and not kb_ext_data:
            return

        # Set device metadata
        self.set_device_type("KBeacon")
        short_addr = short_address(service_info.address)
        self.set_title(f"KBeacon {short_addr}")
        self.set_device_name(f"KBeacon {short_addr}")
        self.set_device_manufacturer("Kkmcn")

        if kb_ext_data:
            self._parse_kb_extension_data(kb_ext_data)

        if not feaa_data:
            return

        _LOGGER.debug("Parsing FEAA data: %s", feaa_data.hex())

        frame_type = feaa_data[0]
        if frame_type == FRAME_TYPE_SENSOR:
            self._parse_sensor_frame(feaa_data)
        elif frame_type == FRAME_TYPE_TLM:
            self._parse_tlm_frame(feaa_data)
        elif frame_type == FRAME_TYPE_SYSTEM:
            self._parse_system_frame(feaa_data)
        elif frame_type == FRAME_TYPE_UID:
            self._parse_uid_frame(feaa_data)
        elif frame_type == FRAME_TYPE_URL:
            self._parse_url_frame(feaa_data)
        else:
            _LOGGER.debug("Unsupported FEAA frame type: 0x%02x", frame_type)

    @staticmethod
    def _service_data_by_uuid(
        service_info: BluetoothServiceInfoBleak,
    ) -> dict[str, bytes]:
        """Map advertisement service data by lowercase UUID string."""
        mapped: dict[str, bytes] = {}
        for uuid_key, value in service_info.service_data.items():
            mapped[str(uuid_key).lower()] = value
        return mapped

    def _parse_kb_extension_data(self, data: bytes) -> None:
        """Parse KBeacon extension service data (UUID 0x2080)."""
        if not data:
            return

        battery_percent = min(data[0], 100)
        self.set_precision(0)
        self.update_predefined_sensor(
            SensorLibrary.BATTERY__PERCENTAGE,
            battery_percent,
        )

        if len(data) > 1:
            beacon_type = data[1]
            _LOGGER.debug(
                "KB extension: battery=%d%% beacon_type=0x%02x raw=%s",
                battery_percent,
                beacon_type,
                data.hex(),
            )
        else:
            _LOGGER.debug(
                "KB extension: battery=%d%% raw=%s", battery_percent, data.hex()
            )

    def _parse_sensor_frame(self, data: bytes) -> None:
        """Parse FEAA frame type 0x21 (KSensor)."""
        if len(data) < 3:
            _LOGGER.debug("Sensor frame too short: %d bytes", len(data))
            return

        sensor_mask = _UNPACK_U16_BE(data[1:3])[0]
        _LOGGER.debug("Sensor mask: 0x%04x", sensor_mask)

        offset = 3
        temperature_value: float | None = None

        if sensor_mask & MASK_VOLTAGE:
            if offset + 2 > len(data):
                return
            voltage_mv = _UNPACK_U16_BE(data[offset : offset + 2])[0]
            self.set_precision(3)
            self.update_predefined_sensor(
                SensorLibrary.VOLTAGE__ELECTRIC_POTENTIAL_VOLT,
                voltage_mv / 1000.0,
            )
            offset += 2

        if sensor_mask & MASK_TEMPERATURE:
            if offset + 2 > len(data):
                return
            temperature_value = _UNPACK_S16_BE(data[offset : offset + 2])[0] / 256.0
            self.set_precision(2)
            self.update_predefined_sensor(
                SensorLibrary.TEMPERATURE__CELSIUS,
                temperature_value,
            )
            offset += 2

        if sensor_mask & MASK_HUMIDITY:
            if offset + 2 > len(data):
                return
            humidity_value = _UNPACK_S16_BE(data[offset : offset + 2])[0] / 256.0
            offset += 2

            # KBeacon SDK uses negative humidity as a packed extension for temperature.
            if humidity_value < 0:
                if temperature_value is not None:
                    temperature_value = (
                        float(100 * (-1 - int(humidity_value))) + temperature_value
                    )
                    self.set_precision(2)
                    self.update_predefined_sensor(
                        SensorLibrary.TEMPERATURE__CELSIUS,
                        temperature_value,
                    )
            else:
                self.set_precision(2)
                self.update_predefined_sensor(
                    SensorLibrary.HUMIDITY__PERCENTAGE,
                    humidity_value,
                )

        if sensor_mask & MASK_ACC:
            if offset + 6 > len(data):
                return
            offset += 6

        if sensor_mask & MASK_CUTOFF:
            if offset + 1 > len(data):
                return
            offset += 1

        if sensor_mask & MASK_PIR:
            if offset + 1 > len(data):
                return
            offset += 1

        if sensor_mask & MASK_LUX:
            if offset + 2 > len(data):
                return
            lux = _UNPACK_U16_BE(data[offset : offset + 2])[0]
            self.set_precision(0)
            self.update_predefined_sensor(SensorLibrary.LIGHT__LIGHT_LUX, lux)
            offset += 2

        if sensor_mask & MASK_VOC:
            if offset + 5 > len(data):
                return
            offset += 5

        if sensor_mask & MASK_CO2:
            if offset + 3 > len(data):
                return
            # First byte is elapsed seconds / 10.
            offset += 1
            co2 = _UNPACK_U16_BE(data[offset : offset + 2])[0]
            self.set_precision(0)
            self.update_predefined_sensor(
                SensorLibrary.CO2__CONCENTRATION_PARTS_PER_MILLION,
                co2,
            )
            offset += 2

        if sensor_mask & MASK_UNREAD_RECORDS:
            if offset + 1 > len(data):
                return
            count_mask = data[offset]
            offset += 1
            if count_mask & 0x01:
                if offset + 2 > len(data):
                    return
                offset += 2

    def _parse_tlm_frame(self, data: bytes) -> None:
        """Parse FEAA frame type 0x20 (Eddystone TLM)."""
        # frame + version + batt + temp + advCount + secCount
        if len(data) < 14:
            _LOGGER.debug("TLM frame too short: %d bytes", len(data))
            return

        battery_mv = _UNPACK_U16_BE(data[2:4])[0]
        temp = _UNPACK_S16_BE(data[4:6])[0] / 256.0

        self.set_precision(3)
        self.update_predefined_sensor(
            SensorLibrary.VOLTAGE__ELECTRIC_POTENTIAL_VOLT,
            battery_mv / 1000.0,
        )
        self.set_precision(2)
        self.update_predefined_sensor(SensorLibrary.TEMPERATURE__CELSIUS, temp)

    def _parse_system_frame(self, data: bytes) -> None:
        """Parse FEAA frame type 0x22 (KBeacon System)."""
        # frame + model + batt + mac(6) + fw(2)
        if len(data) < 11:
            _LOGGER.debug("System frame too short: %d bytes", len(data))
            return

        battery_percent = min(data[2], 100)
        self.set_precision(0)
        self.update_predefined_sensor(
            SensorLibrary.BATTERY__PERCENTAGE,
            battery_percent,
        )

    def _parse_uid_frame(self, data: bytes) -> None:
        """Parse FEAA frame type 0x00 (Eddystone UID)."""
        if len(data) < 20:
            _LOGGER.debug("UID frame too short: %d bytes", len(data))
            return

        _LOGGER.debug(
            "UID frame parsed: tx=%d nid=%s sid=%s",
            int.from_bytes(data[1:2], byteorder="big", signed=True),
            data[2:12].hex(),
            data[12:18].hex(),
        )

    def _parse_url_frame(self, data: bytes) -> None:
        """Parse FEAA frame type 0x10 (Eddystone URL)."""
        if len(data) < 3:
            _LOGGER.debug("URL frame too short: %d bytes", len(data))
            return

        _LOGGER.debug(
            "URL frame parsed: tx=%d", int.from_bytes(data[1:2], "big", signed=True)
        )
