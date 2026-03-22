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
    assert result.devices[None].manufacturer == "KKM Smart Solutions"
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
    """Test that TLM frame (0x20) is parsed."""
    # Frame 0x20, version 0x00, battery 3700mV, temperature 26.5C,
    # adv_count=16, sec_count=100.
    data_string = bytes.fromhex("20000E741A800000001000000064")
    service_info = make_service_info(
        name="KBPro_Test",
        address="BC:57:29:02:45:9F",
        service_uuids=["0000feaa-0000-1000-8000-00805f9b34fb"],
        service_data={"0000feaa-0000-1000-8000-00805f9b34fb": data_string},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    voltage_key = next(k for k in result.entity_values.keys() if k.key == "voltage")
    temperature_key = next(
        k for k in result.entity_values.keys() if k.key == "temperature"
    )

    assert result.entity_values[voltage_key].native_value == 3.7
    assert result.entity_values[temperature_key].native_value == 26.5


def test_kbeacon_unknown_frame_type() -> None:
    """Test that unknown FEAA frame types do not crash parsing."""
    # Unknown frame type 0x99
    data_string = bytes.fromhex("2001070e321b4733b4")
    data_string = b"\x99" + data_string[1:]
    service_info = make_service_info(
        name="KBPro_Test",
        address="BC:57:29:02:45:9F",
        service_uuids=["0000feaa-0000-1000-8000-00805f9b34fb"],
        service_data={"0000feaa-0000-1000-8000-00805f9b34fb": data_string},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    # Device still identified as KBeacon, but no sensor values are added.
    assert result.title == "KBeacon 459F"
    assert not any(
        k.key in {"voltage", "temperature", "humidity", "battery"}
        for k in result.entity_values.keys()
    )


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

    # Device metadata is still set for known KBeacon FEAA advertisements.
    assert result.title == "KBeacon 459F"
    assert not any(
        k.key in {"voltage", "temperature", "humidity", "battery"}
        for k in result.entity_values.keys()
    )


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


def test_kbeacon_system_frame_battery() -> None:
    """Test parsing FEAA system frame (0x22)."""
    # frame=0x22, model=0x01, battery=99, mac=BC:57:29:02:45:9F, fw=1.2
    data_string = bytes.fromhex("220163BC572902459F0102")
    service_info = make_service_info(
        name="KBPro_Test",
        address="BC:57:29:02:45:9F",
        service_uuids=["0000feaa-0000-1000-8000-00805f9b34fb"],
        service_data={"0000feaa-0000-1000-8000-00805f9b34fb": data_string},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    battery_key = next(k for k in result.entity_values.keys() if k.key == "battery")
    assert result.entity_values[battery_key].native_value == 99


def test_kbeacon_uid_frame_no_sensors() -> None:
    """Test parsing FEAA UID frame (0x00) does not add sensor values."""
    # frame=0x00, tx=0xF4, namespace(10)=0, instance(6)=0, RFU(2)=0
    data_string = bytes.fromhex("00F4000000000000000000000000000000000000")
    service_info = make_service_info(
        name="KBPro_UID",
        address="BC:57:29:02:45:9F",
        service_uuids=["0000feaa-0000-1000-8000-00805f9b34fb"],
        service_data={"0000feaa-0000-1000-8000-00805f9b34fb": data_string},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    assert result.title == "KBeacon 459F"
    assert not any(
        k.key in {"voltage", "temperature", "humidity", "battery"}
        for k in result.entity_values.keys()
    )


def test_kbeacon_extension_2080_battery() -> None:
    """Test parsing KBeacon extension service data (0x2080)."""
    # byte0=battery(0x61=97), byte1=beacon flags(0x04), remaining bytes optional.
    ext_data = bytes.fromhex("610401020304")
    service_info = make_service_info(
        name="KBPro_Ext",
        address="BC:57:29:02:45:9F",
        service_uuids=["00002080-0000-1000-8000-00805f9b34fb"],
        service_data={"00002080-0000-1000-8000-00805f9b34fb": ext_data},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    battery_key = next(k for k in result.entity_values.keys() if k.key == "battery")
    assert result.entity_values[battery_key].native_value == 97


def test_kbeacon_sensor_lux_and_co2() -> None:
    """Test parsing 0x21 frame with light and CO2 fields."""
    # frame=0x21, mask=0x0247 (V,T,H,LUX,CO2)
    # voltage=0x0E10(3.600V), temp=0x1A00(26C), hum=0x3200(50%)
    # lux=0x012C(300), co2_elapsed=0x05(50s), co2=0x03E8(1000ppm)
    data_string = bytes.fromhex("2102470E101A003200012C0503E8")
    service_info = make_service_info(
        name="KBPro_CO2",
        address="BC:57:29:02:45:9F",
        service_uuids=["0000feaa-0000-1000-8000-00805f9b34fb"],
        service_data={"0000feaa-0000-1000-8000-00805f9b34fb": data_string},
        manufacturer_data={},
    )

    parser = KBeaconBluetoothDeviceData()
    result = parser.update(service_info)

    light_key = next(k for k in result.entity_values.keys() if k.key == "illuminance")
    co2_key = next(k for k in result.entity_values.keys() if k.key == "carbon_dioxide")

    assert result.entity_values[light_key].native_value == 300
    assert result.entity_values[co2_key].native_value == 1000


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
