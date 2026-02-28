"""
Parser for KBeacon (KBPro) BLE advertisements.

This parser handles KBeacon devices using FEAA frame type 0x21 for sensor data.
"""

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
FRAME_TYPE_SENSOR = 0x21

# Sensor mask bits
MASK_VOLTAGE = 1 << 0  # bit 0: Voltage (2 bytes, mV)
MASK_TEMPERATURE = 1 << 1  # bit 1: Temperature (2 bytes, signed 8.8 fixed point)
MASK_HUMIDITY = 1 << 2  # bit 2: Humidity (2 bytes, 8.8 fixed point)
MASK_ACC = 1 << 3  # bit 3: Accelerometer X,Y,Z (3*2 bytes, mg)
MASK_VOC = 1 << 4  # bit 4: VOC (2 bytes)
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

        # Check if FEAA UUID is present
        if FEAA_UUID not in service_info.service_uuids:
            return

        # Get service data
        service_data_dict = service_info.service_data
        if not service_data_dict:
            return

        # Find the FEAA service data (can be UUID object or string)
        data = None
        for uuid_key, uuid_data in service_data_dict.items():
            uuid_str = str(uuid_key)
            if uuid_str.lower() == FEAA_UUID.lower():
                data = uuid_data
                break

        if not data:
            _LOGGER.debug("FEAA service data not found")
            return

        _LOGGER.debug("Parsing KBeacon service data: %s", data.hex())

        # Validate minimum length (frame type + mask + at least one sensor)
        if len(data) < 5:
            _LOGGER.debug("Service data too short: %d bytes", len(data))
            return

        # Parse frame type
        frame_type = data[0]
        if frame_type != FRAME_TYPE_SENSOR:
            _LOGGER.debug("Unsupported frame type: 0x%02x", frame_type)
            return

        # Parse sensor mask (2 bytes, BIG-endian)
        sensor_mask = _UNPACK_U16_BE(data[1:3])[0]
        _LOGGER.debug("Sensor mask: 0x%04x", sensor_mask)

        # Set device metadata
        self.set_device_type("KBeacon")
        short_addr = short_address(service_info.address)
        self.set_title(f"KBeacon {short_addr}")
        self.set_device_name(f"KBeacon {short_addr}")
        self.set_device_manufacturer("Kkmcn")

        # Parse sensor data using offset walking
        offset = 3  # Start after frame type (1) + mask (2)

        # Voltage (bit 0)
        if sensor_mask & MASK_VOLTAGE:
            if offset + 2 > len(data):
                _LOGGER.debug("Insufficient data for voltage at offset %d", offset)
                return
            voltage_mv = _UNPACK_U16_BE(data[offset : offset + 2])[0]
            voltage_v = voltage_mv / 1000.0
            self.set_precision(3)
            self.update_predefined_sensor(
                SensorLibrary.VOLTAGE__ELECTRIC_POTENTIAL_VOLT, voltage_v
            )
            _LOGGER.debug("Voltage: %d mV (%.3f V)", voltage_mv, voltage_v)
            offset += 2

        # Temperature (bit 1)
        if sensor_mask & MASK_TEMPERATURE:
            if offset + 2 > len(data):
                _LOGGER.debug("Insufficient data for temperature at offset %d", offset)
                return
            temp_raw = _UNPACK_S16_BE(data[offset : offset + 2])[0]
            temp_c = temp_raw / 256.0
            self.set_precision(2)
            self.update_predefined_sensor(SensorLibrary.TEMPERATURE__CELSIUS, temp_c)
            _LOGGER.debug("Temperature: %d raw (%.2f C)", temp_raw, temp_c)
            offset += 2

        # Humidity (bit 2)
        if sensor_mask & MASK_HUMIDITY:
            if offset + 2 > len(data):
                _LOGGER.debug("Insufficient data for humidity at offset %d", offset)
                return
            humidity_raw = _UNPACK_U16_BE(data[offset : offset + 2])[0]
            humidity_percent = humidity_raw / 256.0
            self.set_precision(2)
            self.update_predefined_sensor(
                SensorLibrary.HUMIDITY__PERCENTAGE, humidity_percent
            )
            _LOGGER.debug("Humidity: %d raw (%.2f %%)", humidity_raw, humidity_percent)
            offset += 2

        # Accelerometer (bit 3) - 3 axes, 2 bytes each
        if sensor_mask & MASK_ACC:
            if offset + 6 > len(data):
                _LOGGER.debug(
                    "Insufficient data for accelerometer at offset %d", offset
                )
                return
            # Skip accelerometer data for now (not commonly used in HA)
            _LOGGER.debug("Accelerometer data present (skipping)")
            offset += 6

        # VOC (bit 4) - 2 bytes
        if sensor_mask & MASK_VOC:
            if offset + 2 > len(data):
                _LOGGER.debug("Insufficient data for VOC at offset %d", offset)
                return
            # Skip VOC data for now (format/unit TBD)
            _LOGGER.debug("VOC data present (skipping)")
            offset += 2

        # CO2 (bit 9) - format TBD
        if sensor_mask & MASK_CO2:
            # Format not well documented, cannot safely continue parsing
            _LOGGER.debug(
                "CO2 data present (format TBD, stopping to avoid parsing corruption)"
            )
            return

        # Unread records (bit 10) - 1 byte type + 2 bytes count
        if sensor_mask & MASK_UNREAD_RECORDS:
            if offset + 3 > len(data):
                _LOGGER.debug(
                    "Insufficient data for unread records at offset %d", offset
                )
                return
            _LOGGER.debug("Unread records data present (skipping)")
            offset += 3

        _LOGGER.debug("Parsing complete, final offset: %d", offset)
