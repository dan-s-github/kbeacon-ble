"""Tests for the KBeacon BLE parser."""

from __future__ import annotations

from uuid import UUID

from bleak.backends.device import BLEDevice
from bluetooth_data_tools import monotonic_time_coarse
from habluetooth import BluetoothServiceInfoBleak

from kbeacon_ble import KBeaconBluetoothDeviceData


def test_kbeacon_feaa_frame_0x21_parser() -> None:
    """Test parsing KBeacon FEAA frame type 0x21 with sample payload."""
    # Sample payload from problem statement:
    # "2101070e321b4733b4"
    # - Frame type: 0x21
    # - Sensor mask: 0x0107 (bits 0,1,2 set)
    # - Voltage: 0x0E32 = 3634 mV -> 3.634 V
    # - Temperature: 0x1B47 = 6983 -> 27.277... C
    # - Humidity: 0x33B4 = 13236 -> 51.70%

    data_string = bytes.fromhex("2101070e321b4733b4")
    service_info = make_service_info(
        name="KBPro_142081",
        address="BC:57:29:02:45:9F",
        service_uuids=["0000feaa-0000-1000-8000-00805f9b34fb"],
        service_data={"0000feaa-0000-1000-8000-00805f9b34fb": data_string},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    # Verify device metadata
    assert result.title == "KBeacon 459F"
    assert result.devices[None].name == "KBeacon 459F"
    assert result.devices[None].manufacturer == "Kkmcn"
    assert result.devices[None].model == "KBeacon"

    # Verify sensor values
    assert "voltage" in [k.key for k in result.entity_values.keys()]
    assert "temperature" in [k.key for k in result.entity_values.keys()]
    assert "humidity" in [k.key for k in result.entity_values.keys()]

    # Check specific values
    voltage_key = next(k for k in result.entity_values.keys() if k.key == "voltage")
    temperature_key = next(
        k for k in result.entity_values.keys() if k.key == "temperature"
    )
    humidity_key = next(k for k in result.entity_values.keys() if k.key == "humidity")

    assert result.entity_values[voltage_key].native_value == 3.634
    assert result.entity_values[temperature_key].native_value == 27.28
    assert result.entity_values[humidity_key].native_value == 51.7


def test_kbeacon_voltage_only() -> None:
    """Test parsing with only voltage bit set."""
    # Frame type 0x21, mask 0x0001 (only bit 0), voltage 3000 mV = 0x0BB8
    data_string = bytes.fromhex("2100010BB8")
    service_info = make_service_info(
        name="KBPro_Test",
        address="BC:57:29:02:45:9F",
        service_uuids=["0000feaa-0000-1000-8000-00805f9b34fb"],
        service_data={"0000feaa-0000-1000-8000-00805f9b34fb": data_string},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    assert result.entity_values is not None
    voltage_key = next(k for k in result.entity_values.keys() if k.key == "voltage")
    assert result.entity_values[voltage_key].native_value == 3.0


def test_kbeacon_wrong_frame_type() -> None:
    """Test that wrong frame type is ignored."""
    # Frame type 0x20 (not 0x21), should be ignored
    data_string = bytes.fromhex("2001070e321b4733b4")
    service_info = make_service_info(
        name="KBPro_Test",
        address="BC:57:29:02:45:9F",
        service_uuids=["0000feaa-0000-1000-8000-00805f9b34fb"],
        service_data={"0000feaa-0000-1000-8000-00805f9b34fb": data_string},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    # Should return empty result since frame type is not supported
    assert result.title is None
    assert len(result.entity_values) == 0


def test_kbeacon_short_payload() -> None:
    """Test that short payloads are handled gracefully."""
    # Only 2 bytes (too short)
    data_string = bytes.fromhex("2101")
    service_info = make_service_info(
        name="KBPro_Test",
        address="BC:57:29:02:45:9F",
        service_uuids=["0000feaa-0000-1000-8000-00805f9b34fb"],
        service_data={"0000feaa-0000-1000-8000-00805f9b34fb": data_string},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    # Should return empty result since payload is too short
    assert result.title is None
    assert len(result.entity_values) == 0


def test_kbeacon_no_feaa_uuid() -> None:
    """Test that devices without FEAA UUID are ignored."""
    data_string = bytes.fromhex("2101070e321b4733b4")
    # Use a valid UUID that is not FEAA
    service_info = make_service_info(
        name="KBPro_Test",
        address="BC:57:29:02:45:9F",
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        service_data={"0000fff0-0000-1000-8000-00805f9b34fb": data_string},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    # Should return empty result since FEAA UUID is not present
    assert result.title is None
    assert len(result.entity_values) == 0


def test_kbeacon_temperature_negative() -> None:
    """Test parsing negative temperature values."""
    # Frame type 0x21, mask 0x0002 (only bit 1 for temperature)
    # Temperature -10C = -2560 raw = 0xF600 in signed 16-bit
    data_string = bytes.fromhex("210002F600")
    service_info = make_service_info(
        name="KBPro_Test",
        address="BC:57:29:02:45:9F",
        service_uuids=["0000feaa-0000-1000-8000-00805f9b34fb"],
        service_data={"0000feaa-0000-1000-8000-00805f9b34fb": data_string},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    assert result.entity_values is not None
    temperature_key = next(
        k for k in result.entity_values.keys() if k.key == "temperature"
    )
    assert result.entity_values[temperature_key].native_value == -10.0


def make_service_info(
    name: str,
    address: str,
    service_uuids: list[str],
    service_data: dict[str, bytes],
    manufacturer_data: dict[int, bytes],
    rssi: int = -60,
) -> BluetoothServiceInfoBleak:
    """Create a BluetoothServiceInfoBleak instance for testing."""
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=rssi,
        service_uuids=service_uuids,
        service_data={UUID(k): v for k, v in service_data.items()},
        manufacturer_data=manufacturer_data,
        device=BLEDevice(address=address, name=name, details={}),
        advertisement=None,
        connectable=True,
        time=monotonic_time_coarse(),
        source="local",
        tx_power=0,
    )
