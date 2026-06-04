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

The frame is split in two parts: an 8-byte header, then a **bit-packed
record** that follows the official Victron Solar Sense layout (confirmed
against Victron source code).

### Header (bytes 0..7)

| Index     | Field                               | Notes                                                |
| --------- | ----------------------------------- | ---------------------------------------------------- |
| `0`       | Record type                         | constant `0x10`                                      |
| `1`       | State flag                          | toggles `0x00` ↔ `0x80`, role unknown                |
| `2:3` LE  | Victron product id                  | `0xC050` for the SolarSense 750                      |
| `4`       | —                                   | constant `0xFF`, role unknown                        |
| `5:6` LE  | Message counter / compteur          | 16-bit, useful for RX quality diagnostics            |
| `7`       | —                                   | constant `0x01`, role unknown                        |

### Bit-packed record (bytes 8..23, LSB-first per Victron convention)

Bit offsets are relative to bit 0 of byte 8. Layout and scaling follow
[victronenergy/dbus-ble-sensors `src/solarsense.c`](https://github.com/victronenergy/dbus-ble-sensors/blob/master/src/solarsense.c).

| Bit range  | Field                | Encoding                                              | NA value    |
| ---------- | -------------------- | ----------------------------------------------------- | ----------- |
| `0..31`    | ErrorCode            | UN32 bitmask                                          | —           |
| `32..39`   | Charger Error        | UN8                                                   | `0xFF`      |
| `40..59`   | Installation Power   | UN20, 1 W                                             | `0xFFFFF`   |
| `60..79`   | Today's Yield        | UN20, 0.01 kWh                                        | `0xFFFFF`   |
| `80..93`   | Irradiance           | UN14, 0.1 W/m²                                        | `0x3FFF`    |
| `94..104`  | Cell Temperature     | UN11, 0.1 °C, offset −60 °C                           | `0x7FF`     |
| `105`      | Unspecified Remnant  | 1 bit                                                 | —           |
| `106..113` | Battery Voltage      | UN8, 0.01 V, offset +1.70 V                           | `0xFF`      |
| `114`      | Tx Power Level       | 0 = 0 dBm, 1 = +6 dBm                                 | —           |
| `115..121` | Time Since Last Sun  | UN7, piecewise → minutes (see below)                  | `0x7F`      |

#### Time Since Last Sun quantisation

```
raw 0..29   →  raw * 2 minutes               (0..58 min, 2-min steps)
raw 30..95  →  60 + 10 * (raw - 30) minutes  (60..710 min, 10-min steps)
raw 96..126 →  720 + 30 * (raw - 96) minutes (720..1620 min, 30-min steps)
```

Note: the Cerbo (Venus OS) reports a higher-resolution "Time since last
sun" in seconds, which it computes locally from its VE.Direct connection
to the device. The BLE advertisement field is minutes-only.

### Alarms

Per the Victron source, the only alarm derived from the advertisement is
**LowBattery**: triggers when `BatteryVoltage < 3.2 V`, clears with a
0.4 V hysteresis (i.e. only resets above 3.6 V). The Python decoder
exposes a stateless `low_battery = battery_v < 3.2 V`; the ESPHome
configuration implements the proper hysteresis.

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
--- RSSI -55 dBm ---
  product_id     : 0xC050
  counter        : 20803
  error_code     : 0x04001405
  charger_error  : 0
  pv_power       : 326 W
  yield          : 6900 Wh
  irradiance     : 38.4 W/m²
  cell_temp      : 25.9 °C
  battery_v      : 3.79 V
  low_battery    : False
  tx_power       : +6 dBm
  since_sun      : 42 min
  state_flag     : 0x00
  bytes/octets   : 0:10 1:00 2:50 3:c0 4:ff 5:43 6:51 7:01 8:05 ...
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

Three stages:

1. **Differential analysis** on a series of live captures established that
   the payload is unencrypted (the payload is nearly constant while the
   message counter increments — a ciphertext under a counter would change
   on every byte) and identified PV power, irradiance, cell temperature
   and today's yield empirically against the VictronConnect app.
2. **Cross-check against the Victron Solar Sense field table** (kindly
   shared by a Victron developer) confirmed the layout is a bit-packed
   record starting at byte 8.
3. **Alignment with the Victron source** at
   [dbus-ble-sensors `src/solarsense.c`](https://github.com/victronenergy/dbus-ble-sensors/blob/master/src/solarsense.c)
   confirmed every scaling factor, validated the header magic bytes
   (`buf[0] == 0x10`, `buf[4] == 0xFF`, `buf[7] == 0x01`), and provided
   the non-linear Time Since Last Sun quantisation as well as the
   LowBattery alarm thresholds.

## Use it from Home Assistant via ESPHome

An [ESPHome configuration](esphome/solarsense.yaml) is provided. Flash it
to any ESP32 within BLE range of the sensor and you get **nine entities**
in Home Assistant — six numeric sensors (irradiance, installation power,
today's yield, cell temperature, battery voltage, time since last sun),
two diagnostic text sensors (error code, charger error) and one
binary sensor (low battery) — all with the right `device_class` /
`state_class`. The yield is exposed as `total_increasing` in kWh so it
plugs straight into HA's Energy dashboard, and the Low Battery sensor
implements Victron's official 3.2 V trip / 3.6 V release hysteresis.

The same ESP32 also runs the standard ESPHome `bluetooth_proxy:` component
in **active** mode, so it can serve as a full Bluetooth proxy for the
rest of your HA Bluetooth devices (Xiaomi, Govee, Switchbot, official
Victron, …).

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
   nine entities (six numeric sensors, two text sensors and the Low
   Battery binary sensor) are added automatically.

> **BLE range tip.** The SolarSense is a low-power broadcaster — RSSI
> around −98 dBm has been observed at night when the radio backs off.
> For reliable reception, place the ESP32 as close to the sensor as
> possible (same roof / same room ideally).

### Why decode on the ESP32 rather than pure BLE proxy?

The `bluetooth_proxy:` component alone would forward the SolarSense
advertisements to Home Assistant, but no HA integration currently knows
how to decode this device. Decoding inside ESPHome turns the frames into
clean, typed sensors immediately, while still leaving the ESP32 available
as a proxy for everything else.

## Status / Statut

- ✅ Installation Power, Today's Yield, Irradiance, Cell Temperature,
  Battery Voltage, Charger Error, Tx Power Level, Time Since Last Sun
  (in minutes), LowBattery alarm — all validated against the Victron
  source code
- ✅ ErrorCode exposed as raw 32-bit bitmask; individual bit meanings not
  mapped here (would need additional Victron documentation)
- ✅ Message counter (16-bit) and Victron product id (`0xC050`) — useful
  for filtering and RX quality diagnostics
- ✅ Header magic bytes (`0x10`, `0xFF`, `0x01` at indices 0, 4, 7)
  validated, matching the Victron source check
- 🟡 Byte 1 of the header (toggles `0x00`/`0x80`) — not validated by the
  Victron source, role unknown
- Contributions welcome

## Credits / Remerciements

This project would not have come together without:

- [**@imval**](https://github.com/imval) — shared the Victron Solar Sense
  field table in
  [issue #1](https://github.com/tukutt/Victron-SolarSense-750-EspHome/issues/1)
  of this repository, which unlocked the bit-packed layout.
- **ju@workshop** from the
  [Réseautonome Discord](https://discord.gg/ZUWtePfyDF) (channel
  `#blabla-élec-et-photovoltaïque`) — pointed to the official Victron
  source [`dbus-ble-sensors/src/solarsense.c`](https://github.com/victronenergy/dbus-ble-sensors/blob/master/src/solarsense.c),
  which let us verify every scaling factor, the non-linear "Time Since
  Last Sun" quantisation, and the LowBattery alarm thresholds.

Merci !

## Disclaimer

This project is **not affiliated with Victron Energy**. It relies on public
BLE advertisements and is provided for interoperability and educational
purposes. Use at your own risk.

## License

MIT
