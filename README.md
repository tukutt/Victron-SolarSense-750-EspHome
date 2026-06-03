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

| Index     | Field                               | Notes                                                |
| --------- | ----------------------------------- | ---------------------------------------------------- |
| `0`       | Record type                         | constant `0x10`                                      |
| `1`       | State flag                          | toggles `0x00` ↔ `0x80`, meaning unknown             |
| `2:3` LE  | Victron product id                  | `0xC050` for the SolarSense 750                      |
| `4`       | —                                   | constant `0xFF`, role unknown                        |
| `5:6` LE  | Message counter / compteur          | 16-bit, useful for RX quality diagnostics            |
| `7:9`     | —                                   | constant `0x01 0x05 0x14`, role unknown              |
| `10:12`   | —                                   | constant `0x00 0x04 0x00`                            |
| `13:14`   | Estimated PV power / puissance PV   | watts (W)                                            |
| `15:16`   | Today's yield                       | `raw * 0.625` → Wh (validated on 3 datapoints)       |
| `17`      | —                                   | constant `0x00`                                      |
| `18:19`   | Irradiance                          | `raw & 0x3FFF` then `/ 10` → W/m²                    |
| `19` MSB  | Status flags                        | top 2 bits; `11` in sunlight, `10` in darkness       |
| `20`      | Cell temperature / température      | `(raw - 150) * 0.4` → °C, 0.4 °C resolution          |
| `21`      | Diagnostic byte                     | varies (`0x42`, `0x46`, `0x4a` seen), role unknown   |
| `22:23`   | —                                   | constant `0x07 0xfc` (not a CRC)                     |

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
--- RSSI -48 dBm ---
  product_id   : 0xC050
  counter      : 13990
  irradiance   : 46.0 W/m²   (flags=11)
  pv_power     : 391 W
  yield        : 6630.0 Wh        (raw=10608)
  cell_temp    : 23.2 °C
  state_flag   : 0x80
  diag_21      : 0x42
  bytes/octets : 0:10 1:80 2:50 3:c0 4:ff 5:a6 6:36 7:01 8:05 9:14 ...
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

## Use it from Home Assistant via ESPHome

An [ESPHome configuration](esphome/solarsense.yaml) is provided. Flash it to
any ESP32 within BLE range of the sensor and you get four native sensors
in Home Assistant — irradiance, PV power, today's yield, cell temperature —
with proper `device_class` / `state_class` (the yield is exposed as
`total_increasing` so it plugs straight into HA's Energy dashboard).

The same ESP32 also runs the standard ESPHome `bluetooth_proxy:` component,
so it can serve as a regular Bluetooth proxy for the rest of your HA
Bluetooth devices (Xiaomi, Govee, Switchbot, official Victron, …).

### Setup

1. Edit `esphome/solarsense.yaml` and adjust `name`, `friendly_name`,
   `min_version`, etc. to match your setup.
2. Add to your ESPHome `secrets.yaml`:
   ```yaml
   wifi_ssid: "your-ssid"
   wifi_password: "your-password"
   solarsense_mac: "AA:BB:CC:DD:EE:FF"
   ```
3. Compile and flash:
   ```bash
   esphome run esphome/solarsense.yaml
   ```
4. The ESP32 appears in Home Assistant via the ESPHome integration; the
   four `SolarSense …` sensors are added automatically.

### Why decode on the ESP32 rather than pure BLE proxy?

The `bluetooth_proxy:` component alone would forward the SolarSense
advertisements to Home Assistant, but no HA integration currently knows
how to decode this device. Decoding inside ESPHome turns the frames into
clean, typed sensors immediately, while still leaving the ESP32 available
as a proxy for everything else.

## Status / Statut

- ✅ Irradiance, PV power, cell temperature, 16-bit message counter
- ✅ Today's yield — formula `raw * 0.625` Wh validated against
  VictronConnect on 3 datapoints (10608→6630, 10672→6670, 10736→6710 Wh)
- ✅ Victron product id (`0xC050`) — cross-validated with the Venus OS
  "Device" page in VictronConnect
- 🟡 Status flags (top 2 bits of byte 19) — 4 states observed (`00`/`01`/
  `10`/`11`), no simple correlation with light level; could be gain/range
  selection
- 🟡 Byte 1 (state flag, toggles `0x00`/`0x80`) and byte 21 (diagnostic,
  values `0x42`/`0x46`/`0x4a`) — role unknown
- ✅ Bytes 22:23 (`0x07 0xfc`) confirmed constant, NOT a CRC
- Contributions welcome

## Disclaimer

This project is **not affiliated with Victron Energy**. It relies on public
BLE advertisements and is provided for interoperability and educational
purposes. Use at your own risk.

## License

MIT
