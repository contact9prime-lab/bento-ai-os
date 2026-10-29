# An ESP32 on your bench, read and switched by Bento

This is the warehouse from [ESP32 nodes on a Pi](network.md#esp32-nodes-on-a-pi), shrunk to one
board on a desk. An ESP32-S3 with a microphone, a touch pad, a vibration switch, a small screen, its
own RGB LED and a speaker becomes part of a Pi set up from your hub. Then you ask your agent about it
in chat, and it asks you before it switches anything.

The firmware is [ESPHome](https://esphome.io). Bento talks to the board's ESPHome web server, so
anything ESPHome supports can be added later without touching Bento.

## What you need

| Part | Used for |
|---|---|
| ESP32-S3 DevKit N16R8 | the node |
| INMP441 I2S microphone | Sound level, in dB |
| MAX98357 I2S amplifier and a 1.5" speaker | Alarm, a chime that repeats until switched off |
| TTP223 touch pad | Touch |
| SW-18010P vibration switch | Vibration (a knock on the table) |
| 0.91" OLED, 128x32, I2C | shows sound, touch and vibration on the board |
| The board's own RGB LED | Status LED, switched from chat |
| Jumper wires, multimeter | wiring, and checking 3.3 V and 5 V before plugging anything in |
| 18650 cell, holder, slide switch, Type-C boost and charger | running it on battery, later |

Not needed here: the ATtiny85 (it can't run ESPHome) and the CR2032 cells. The round 1.28" GC9A01
display can come later; ESPHome drives it too.

You also need a Pi that your hub set up (a Zero), on the same Wi-Fi as the board.

## Wiring

GPIO 35, 36 and 37 belong to the N16R8's memory chip. Never wire anything to them.

| From | To on the ESP32-S3 |
|---|---|
| OLED SDA, SCL | GPIO8, GPIO9 |
| OLED VCC, GND | 3V3, GND |
| Touch pad OUT | GPIO4 |
| Touch pad VCC, GND | 3V3, GND |
| Vibration switch | one leg to GPIO5, the other to GND |
| INMP441 SCK, WS, SD | GPIO12, GPIO13, GPIO11 |
| INMP441 L/R | GND (left channel) |
| INMP441 VDD, GND | 3V3, GND |
| MAX98357 BCLK, LRC, DIN | GPIO15, GPIO16, GPIO17 |
| MAX98357 VIN, GND | 5V, GND |
| Speaker | MAX98357 + and − |

The RGB LED is on the board, on GPIO48. Some boards (revision 1.1) have it on GPIO38: change
`led_pin` at the top of the file if yours doesn't light.

Power it from USB first. For the battery later: 18650 → slide switch → the boost board's input, and
the boost board's 5 V output to the ESP32's 5V pin. Check the boost board's output with the
multimeter before connecting it.

## Flash it

1. Install ESPHome on your computer: `pip install esphome`.
2. Copy [`packaging/esphome/bento-bench.yaml`](../packaging/esphome/bento-bench.yaml) to a folder,
   and next to it a `secrets.yaml`:

   ```yaml
   wifi_ssid: "your Wi-Fi"
   wifi_password: "its password"
   api_key: "paste the output of: openssl rand -base64 32"
   ota_password: "any password"
   web_password: "the password Bento will use"
   ```

3. Plug the board in with the USB-C port marked **COM** or **UART**, and run
   `esphome run bento-bench.yaml`. If it can't connect, hold **BOOT**, tap **RST**, let go of BOOT.
4. Open `http://bench-1.local` in a browser, sign in as `bento` with your web password, and you'll
   see every value it reports. Touch the pad, tap the table, clap.

## Give it to your Pi

On the hub, in Devices, open your Pi's **Hardware** and press **ESP32 nodes**:

1. **Find on its network**. `bench-1` should answer, because its YAML has `api:`.
2. Press **Add** next to it, type `bento` and your web password, and **Add node**. The Pi reads the
   board first, and keeps it only if it answers. The password goes into the Pi's vault.
3. Its things are now on the Pi's hardware list as `<pi>/esp.bench-1.…`. Press
   **What agents may use** and allow what you want: Read for the sensors, Read and set for the
   Status LED and the Alarm.

From a terminal on the hub it's the same:

```
bento network esp my-pi find
bento network esp my-pi add bench-1 192.168.1.57 --user bento
bento network permit my-pi esp.bench-1.sensor.chip_temperature read
bento network permit my-pi esp.bench-1.light.status_led set
```

## Try it

In any chat on the hub:

- "What's the bench's chip temperature and sound level?"
- "Has anyone touched the bench?" (touch the pad first)
- "Is the table vibrating?" (knock on it)
- "Turn on the status LED on the bench." You're asked first, then it's read back from the board.
- "Sound the alarm on the bench." Asked, then the speaker chimes every 3 seconds until you say
  "turn the alarm off".

Every value is sampled every 10 seconds and kept for 90 days. In Devices, tap a reading to see its
chart. Clap a few times and the sound level shows it.

What else you can read straight off the board: Wi-Fi signal, uptime, free memory, its IP address
and its ESPHome version. Those are the board's own numbers, useful for checking a node's health.

## If something doesn't work

- **Find shows nothing.** The board and the Pi must be on the same network, and mDNS must reach
  between them (guest networks and some mesh Wi-Fi block it). Add it by its IP address instead.
- **"it wants a password"**: the user or password doesn't match `web_server: auth:` in the YAML.
- **"is web_server on in its YAML?"**: the board answered, but not with ESPHome's web server.
- **No sound level**: check the INMP441's L/R pin is on GND and the three I2S wires.
- **Status LED never lights**: try `led_pin: GPIO38`.
- **OLED blank**: some modules are at address `0x3D`.

## How this was tested

The YAML was checked with ESPHome 2026.6.5 (`esphome config`). Bento was tested against a stand-in
that serves exactly these entities over ESPHome's own web server API
(`agentos/demos/esp_sim.py`, layout `bench`; `tests/test_esp_nodes.py`). It hasn't been run
on a real board yet. The first person to flash one will be the first real test.
