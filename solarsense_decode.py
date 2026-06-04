#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["bleak"]
# ///
"""
solarsense_decode.py  (v3 - aligned with official Victron source)
-----------------------------------------------------------------
EN: The Victron SolarSense 750 broadcasts its Instant Readout measurements
    IN PLAINTEXT (no AES encryption), as a bit-packed record. The layout
    matches the Victron reference implementation in
    https://github.com/victronenergy/dbus-ble-sensors/blob/master/src/solarsense.c

FR: Le Victron SolarSense 750 diffuse ses mesures Instant Readout EN CLAIR
    (pas de chiffrement AES) sous forme de bit-field. L'implémentation suit
    le code source officiel Victron (lien ci-dessus).

Tested firmware / Firmware testé : 1.01

Frame layout (24 bytes, manufacturer id 0x02E1):

  Header (bytes 0..7) — validated as protocol magic by the Victron source:
    idx 0        : 0x10 record type (validated)
    idx 1        : flag, toggles 0x00 <-> 0x80; NOT validated by source
    idx 2:3 LE   : Victron product id — 0xC050 for the SolarSense 750
    idx 4        : 0xFF (validated magic byte)
    idx 5:6 LE   : message counter (16-bit) — useful for RX diagnostics
    idx 7        : 0x01 (validated magic byte)

  Bit-packed Solar Sense record (bytes 8..23, bit offsets relative to bit 0
  of byte 8, LSB-first per Victron convention):
    bits   0..31 : ErrorCode                  (UN32, raw bitmask)
    bits  32..39 : Charger Error              (UN8,  NA=0xFF)
    bits  40..59 : Installation Power         (UN20, 1 W,         NA=0xFFFFF)
    bits  60..79 : Today's Yield              (UN20, 0.01 kWh,    NA=0xFFFFF)
    bits  80..93 : Irradiance                 (UN14, 0.1 W/m²,    NA=0x3FFF)
    bits  94..104: Cell Temperature           (UN11, 0.1 °C, offset -60 °C,
                                                NA=0x7FF)
    bit  105     : Unspecified Remnant
    bits 106..113: Battery Voltage            (UN8,  0.01 V, offset +1.70 V,
                                                NA=0xFF)
    bit  114     : Tx Power Level             (0 = 0 dBm, 1 = +6 dBm)
    bits 115..121: Time Since Last Sun        (UN7, NA=0x7F, non-linear
                                                quantisation -> minutes,
                                                see _tss_minutes() below)

Alarms (per Victron source):
    LowBattery: triggers when BatteryVoltage < 3.2 V, hysteresis 0.4 V
    (stateless: this decoder simply reports voltage < 3.2 V)

Usage:
    SOLARSENSE_MAC=XX:XX:XX:XX:XX:XX uv run solarsense_decode.py scan
    uv run solarsense_decode.py decode <hex>
"""

import os
import sys
import binascii

MAC = os.environ.get("SOLARSENSE_MAC", "XX:XX:XX:XX:XX:XX")
VICTRON_MANUFACTURER_ID = 0x02E1
SOLARSENSE_750_PRODUCT_ID = 0xC050

# Bit-packed record starts at byte 8 of the frame
RECORD_OFFSET = 8


def _bits(data: bytes, start: int, length: int) -> int:
    """Read `length` bits starting at bit offset `start` (LSB-first)."""
    value = 0
    for i in range(length):
        bit_index = start + i
        value |= ((data[bit_index // 8] >> (bit_index % 8)) & 1) << i
    return value


def _tss_minutes(raw: int) -> int:
    """Time Since Last Sun: piecewise quantisation from Victron source.

    raw 0..29   -> raw * 2 minutes              (0..58, 2-min steps)
    raw 30..95  -> 60 + 10 * (raw - 30) minutes (60..710, 10-min steps)
    raw 96..126 -> 720 + 30 * (raw - 96) minutes (720..1620, 30-min steps)
    """
    if raw <= 29:
        return raw * 2
    if raw <= 95:
        return 60 + 10 * (raw - 30)
    if raw <= 126:
        return 720 + 30 * (raw - 96)
    return raw


def parse(data: bytes) -> dict:
    # Victron source validates byte 0, byte 4 and byte 7 as protocol magic
    if (
        len(data) < 24
        or data[0] != 0x10
        or data[4] != 0xFF
        or data[7] != 0x01
    ):
        raise ValueError(f"Unexpected frame / trame inattendue : {data.hex()}")

    # Header
    product_id = int.from_bytes(data[2:4], "little")
    counter = int.from_bytes(data[5:7], "little")
    state_flag = data[1]

    # Bit-packed record (bytes 8..23)
    rec = data[RECORD_OFFSET:]
    error_code = _bits(rec, 0, 32)
    charger_error_raw = _bits(rec, 32, 8)
    pv_power_raw = _bits(rec, 40, 20)
    yield_raw = _bits(rec, 60, 20)
    irradiance_raw = _bits(rec, 80, 14)
    cell_temp_raw = _bits(rec, 94, 11)
    battery_raw = _bits(rec, 106, 8)
    tx_power_high = _bits(rec, 114, 1)
    since_sun_raw = _bits(rec, 115, 7)

    battery_v = None if battery_raw == 0xFF else 1.70 + battery_raw * 0.01

    return {
        "raw": data,
        # Header
        "product_id": product_id,
        "counter": counter,
        "state_flag": state_flag,
        # Decoded fields (None when the field carries its NA value)
        "error_code": error_code,
        "charger_error": None if charger_error_raw == 0xFF else charger_error_raw,
        "pv_power": None if pv_power_raw == 0xFFFFF else pv_power_raw,
        "yield_wh": None if yield_raw == 0xFFFFF else yield_raw * 10,
        "irradiance": None if irradiance_raw == 0x3FFF else irradiance_raw * 0.1,
        "cell_temp": None if cell_temp_raw == 0x7FF else cell_temp_raw * 0.1 - 60,
        "battery_v": battery_v,
        "tx_power_dbm": 6 if tx_power_high else 0,
        "since_sun_min": None if since_sun_raw == 0x7F else _tss_minutes(since_sun_raw),
        # Stateless low-battery flag (real alarm uses 0.4 V hysteresis)
        "low_battery": None if battery_v is None else battery_v < 3.2,
    }


def _fmt(value, fmt, na="—"):
    return na if value is None else format(value, fmt)


def show(r: dict) -> None:
    print(f"  product_id     : 0x{r['product_id']:04X}")
    print(f"  counter        : {r['counter']}")
    print(f"  error_code     : 0x{r['error_code']:08x}")
    print(f"  charger_error  : {_fmt(r['charger_error'], 'd')}")
    print(f"  pv_power       : {_fmt(r['pv_power'], 'd')} W")
    print(f"  yield          : {_fmt(r['yield_wh'], '.0f')} Wh")
    print(f"  irradiance     : {_fmt(r['irradiance'], '.1f')} W/m²")
    print(f"  cell_temp      : {_fmt(r['cell_temp'], '.1f')} °C")
    print(f"  battery_v      : {_fmt(r['battery_v'], '.2f')} V")
    print(f"  low_battery    : {r['low_battery']}")
    print(f"  tx_power       : +{r['tx_power_dbm']} dBm")
    print(f"  since_sun      : {_fmt(r['since_sun_min'], 'd')} min")
    print(f"  state_flag     : 0x{r['state_flag']:02x}")
    d = r["raw"]
    print("  bytes/octets   : " + " ".join(f"{i}:{d[i]:02x}" for i in range(len(d))))
    print()


def mode_decode(hex_str: str) -> None:
    data = binascii.unhexlify(hex_str.strip().replace(" ", "").replace(":", ""))
    print(f"\nFrame/Trame ({len(data)} bytes/octets) : {data.hex()}\n")
    show(parse(data))


def mode_scan() -> None:
    import asyncio
    from bleak import BleakScanner

    target = MAC.upper()
    if target == "XX:XX:XX:XX:XX:XX":
        sys.exit(
            "Sensor MAC not configured / MAC du capteur non configurée. "
            "Set SOLARSENSE_MAC=AA:BB:CC:DD:EE:FF in your environment."
        )
    print(f"Scanning… / Scan en cours… (target/cible {target}, Ctrl+C to stop)\n")

    def callback(device, adv):
        if device.address.upper() != target:
            return
        md = adv.manufacturer_data.get(VICTRON_MANUFACTURER_ID)
        if not md:
            return
        try:
            r = parse(md)
        except ValueError as exc:
            print(f"[!] {exc}")
            return
        print(f"--- RSSI {adv.rssi} dBm ---")
        show(r)

    async def runner():
        scanner = BleakScanner(detection_callback=callback)
        await scanner.start()
        try:
            while True:
                await asyncio.sleep(1)
        finally:
            await scanner.stop()

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        print("\nStopped / Arrêt.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("scan", "decode"):
        sys.exit(__doc__)
    if sys.argv[1] == "scan":
        mode_scan()
    else:
        if len(sys.argv) < 3:
            sys.exit(
                "Provide the hex frame / fournis la trame hex : "
                "uv run solarsense_decode.py decode <hex>"
            )
        mode_decode(sys.argv[2])


if __name__ == "__main__":
    main()
