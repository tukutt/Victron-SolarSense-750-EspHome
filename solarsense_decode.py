#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["bleak"]
# ///
"""
solarsense_decode.py  (v2 - plaintext frames, no key needed)
------------------------------------------------------------
EN: The Victron SolarSense 750 broadcasts its Instant Readout measurements
    IN PLAINTEXT (no AES encryption) — confirmed by differential analysis
    (the payload is nearly constant while the message counter increments,
    bytes are strongly structured). The bindkey is therefore NOT required.

FR: Le Victron SolarSense 750 diffuse ses mesures Instant Readout EN CLAIR
    (pas de chiffrement AES) : confirmé par analyse différentielle (payload
    quasi constant alors que le compteur de messages s'incrémente, octets
    fortement structurés). La bindkey n'est donc PAS nécessaire.

Tested firmware / Firmware testé : 1.01

Mapping / Trame 24 bytes, manufacturer id 0x02E1:
    idx 0        : 0x10 record type (constant)
    idx 1        : status flag, toggles 0x00 <-> 0x80 (meaning unknown)
    idx 2:3 LE   : Victron product id — 0xC050 for the SolarSense 750
    idx 4        : 0xFF (constant, role unknown)
    idx 5:6 LE   : message counter / compteur de messages (16-bit) — useful
                   for RX quality diagnostics
    idx 7:9      : 0x01 0x05 0x14 (constant, role unknown)
    idx 10:12    : 0x00 0x04 0x00 (constant)
    idx 13:14 LE : estimated PV power / puissance PV estimée (W)
    idx 15:16 LE : today's yield — raw * 0.625  -> Wh
                   (Wh = raw * 5 / 8 ; validated against VictronConnect on
                   3 datapoints — 10608→6630, 10672→6670, 10736→6710 Wh)
    idx 17       : 0x00 (constant)
    idx 18:19 LE : irradiance, & 0x3FFF then / 10  -> W/m²
                   (top 2 bits of idx19 = status flags; 11 seen in sunlight,
                   10 in darkness — meaning to confirm)
    idx 20       : cell temperature / température cellule
                   (raw - 150) * 0.4  -> °C, 0.4 °C resolution
    idx 21       : diagnostic byte, varies but not monotonically with power
                   or temperature (values 0x42, 0x46, 0x4a observed) — role
                   unknown
    idx 22:23    : 0x07 0xfc constant (NOT a CRC)

Dependencies / Dépendances : bleak (uv installs it automatically via the
PEP 723 header above / uv l'installe seul via l'en-tête PEP 723 ci-dessus)

Usage:
    SOLARSENSE_MAC=XX:XX:XX:XX:XX:XX uv run solarsense_decode.py scan
    uv run solarsense_decode.py decode <hex>

EN: Configure the sensor MAC address through the SOLARSENSE_MAC environment
    variable (or edit the default constant below).
FR: La MAC du capteur se configure via la variable d'environnement
    SOLARSENSE_MAC (ou en éditant la constante par défaut ci-dessous).
"""

import os
import sys
import binascii

MAC = os.environ.get("SOLARSENSE_MAC", "XX:XX:XX:XX:XX:XX")
VICTRON_MANUFACTURER_ID = 0x02E1


def s16(v):
    return v - 0x10000 if v >= 0x8000 else v


YIELD_SCALE_WH = 0.625  # idx15:16 * 0.625 = today's yield in Wh
SOLARSENSE_750_PRODUCT_ID = 0xC050


def parse(data: bytes) -> dict:
    # EN: Validate header byte / FR: validation de l'en-tête
    if len(data) < 24 or data[0] != 0x10:
        raise ValueError(f"Unexpected frame / trame inattendue : {data.hex()}")
    product_id = int.from_bytes(data[2:4], "little")
    counter = int.from_bytes(data[5:7], "little")
    pv_power = int.from_bytes(data[13:15], "little")
    yield_raw = int.from_bytes(data[15:17], "little")
    yield_wh = yield_raw * YIELD_SCALE_WH
    raw_irr = int.from_bytes(data[18:20], "little")
    irradiance = (raw_irr & 0x3FFF) / 10.0
    irr_flags = data[19] >> 6
    cell_temp = (data[20] - 150) * 0.4
    return {
        "raw": data,
        "product_id": product_id,
        "counter": counter,
        "pv_power": pv_power,
        "yield_raw": yield_raw,
        "yield_wh": yield_wh,
        "irradiance": irradiance,
        "irr_flags": irr_flags,
        "cell_temp": cell_temp,
        # EN: bytes whose role is not yet confirmed — exposed for debugging
        # FR: octets non encore identifiés — exposés pour debug
        "state_flag": data[1],
        "diag_21": data[21],
    }


def show(r: dict) -> None:
    print(f"  product_id   : 0x{r['product_id']:04X}")
    print(f"  counter      : {r['counter']}")
    print(f"  irradiance   : {r['irradiance']:.1f} W/m²   (flags={r['irr_flags']:02b})")
    print(f"  pv_power     : {r['pv_power']} W")
    print(f"  yield        : {r['yield_wh']:.1f} Wh        (raw={r['yield_raw']})")
    print(f"  cell_temp    : {r['cell_temp']:.1f} °C")
    print(f"  state_flag   : 0x{r['state_flag']:02x}")
    print(f"  diag_21      : 0x{r['diag_21']:02x}")
    d = r["raw"]
    # EN: byte dump to help further reverse-engineering
    # FR: dump des octets pour poursuivre le reverse
    print("  bytes/octets : " + " ".join(f"{i}:{d[i]:02x}" for i in range(len(d))))
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
