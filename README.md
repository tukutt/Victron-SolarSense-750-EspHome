# victron-solarsense750

Decode the BLE Instant Readout frames broadcast by the **Victron SolarSense 750**
pyranometer — **no bindkey required**.

Décodeur des trames BLE Instant Readout du pyranomètre **Victron SolarSense 750**
— **pas besoin de bindkey**.

---

## TL;DR

The SolarSense 750 advertises its measurements **in plaintext** under the
Victron manufacturer id `0x02E1`. This repo provides a small, dependency-light
Python script that scans for the device and decodes the payload live, or
decodes a pasted hex frame offline.

Le SolarSense 750 diffuse ses mesures **en clair** sous le manufacturer id
Victron `0x02E1`. Ce dépôt fournit un petit script Python qui scanne le
capteur et décode la charge utile en direct, ou décode une trame hex collée.

**Tested firmware / Firmware testé :** `1.01`

## Decoded fields / Champs décodés

24-byte frame, little-endian where applicable:

| Index    | Field                               | Notes                                          |
| -------- | ----------------------------------- | ---------------------------------------------- |
| `5`      | Message counter / compteur          | ignore                                         |
| `13:14`  | Estimated PV power / puissance PV   | watts (W)                                      |
| `18:19`  | Irradiance                          | `raw & 0x3FFF` then `/ 10` → W/m²              |
| `19` MSB | Status flags                        | top 2 bits of byte 19                          |
| `20`     | Cell temperature / température      | `(raw - 150) * 0.4` → °C, 0.4 °C resolution    |

## Requirements

- Python ≥ 3.9
- A BLE adapter (built-in or USB)
- [`uv`](https://docs.astral.sh/uv/) (recommended — handles the dependency
  automatically via the [PEP 723](https://peps.python.org/pep-0723/) header)

The only runtime dependency is [`bleak`](https://github.com/hbldh/bleak).

## Usage

### 1. Live scan / Scan en direct

Configure the sensor MAC address with the `SOLARSENSE_MAC` environment
variable, then run:

```bash
export SOLARSENSE_MAC=AA:BB:CC:DD:EE:FF
uv run solarsense_decode.py scan
```

Sample output:

```
--- RSSI -62 dBm ---
  counter      : 142
  irradiance   : 824.3 W/m²   (flags=00)
  pv_power     : 187 W
  cell_temp    : 41.6 °C
  bytes/octets : 0:10 1:e1 2:02 3:... ...
```

### 2. Offline decode / Décodage hors-ligne

```bash
uv run solarsense_decode.py decode 10e102a0...<full hex>
```

Spaces and colons in the hex string are ignored.

## Finding the MAC

Any BLE scanner will do. With `bleak`:

```bash
uv run --with bleak python -c "import asyncio,bleak; \
print(asyncio.run(bleak.BleakScanner.discover()))"
```

Or use `bluetoothctl scan on`, nRF Connect, LightBlue, etc. The device
advertises as a Victron product with manufacturer id `0x02E1`.

## How it was reverse-engineered

Differential analysis on a long capture:

- The payload is nearly constant while the message counter at index `5`
  increments → the frame is **not encrypted** (a ciphertext under a counter
  would change on every byte).
- Byte positions correlate with known physical readings (irradiance, PV
  power) and follow Victron's typical little-endian layout for Instant
  Readout records.
- The cell temperature mapping was confirmed by capturing frames at varying
  ambient temperatures.

## Status / Statut

- ✅ Irradiance, PV power, cell temperature
- 🟡 Status flags (top 2 bits of byte 19) — meaning not yet fully confirmed
- 🟡 Remaining bytes — likely sensor health / diagnostics, contributions
  welcome

## Disclaimer

This project is **not affiliated with Victron Energy**. It relies on public
BLE advertisements and is provided for interoperability and educational
purposes. Use at your own risk.

## License

MIT
