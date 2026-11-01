# Add your sensor

Bento reads boards that run [ESPHome](https://esphome.io). If ESPHome supports your sensor, Bento
can probably read it today with no code. This page goes from that up to a pull request.

## 1. Any ESPHome board already works

Give the board ESPHome's web server and it shows up as items on the Pi that looks after it:

```yaml
web_server:
  port: 80
  version: 3
  auth:            # optional, and kept in the Pi's vault
    username: admin
    password: !secret web_password
```

Then add it from Devices → Hardware → **ESP32 nodes**, or from a terminal:

```bash
bento network esp pi-kitchen find                    # who answers on its network
bento network esp pi-kitchen add plant-1 10.0.4.30   # read it, then keep it
```

These kinds of entity come across: `sensor`, `binary_sensor` (a contact), `text_sensor`, and
`switch`, `light` and `fan`, which can also be switched. Every switch an agent makes is asked of
you first. A full working example is
[`packaging/esphome/bento-bench.yaml`](../packaging/esphome/bento-bench.yaml), walked through in
[An ESP32 on your bench](esp32-bench.md).

Once it's in, a reading can start a mission ("when the soil is drier than 30% for 10 minutes"):
see [Missions → device triggers](missions.md).

## 2. Share your board (a good first PR)

You built something that works. Add its YAML as `packaging/esphome/<name>.yaml`, with secrets as
`!secret` and no Wi-Fi password in the file. Put a short table at the top of the file: the parts,
which pin goes where, and what each entity is for. That's the whole PR, and it saves the next
person an evening.

## 3. Teach the simulator your board (no hardware needed)

The warehouse demo's boards are [`agentos/demos/esp_sim.py`](../agentos/demos/esp_sim.py). It
speaks ESPHome's own web server API and mDNS, so Bento can't tell it from a flashed board. To add
yours:

1. Add a `_make_<kind>` method that lists its entities with `self.add(domain, name, value, unit)`,
   using the same names as your YAML.
2. If its values should move, add a branch for your kind in `tick()`. A greenhouse warms in the
   day and cools when its vent opens; a little physics makes the charts look real.
3. Add it to a layout in `LAYOUTS`, then run it:

   ```bash
   python agentos/demos/esp_sim.py --layout <yours> --base 18600 --control 18699
   ```

4. Add a test beside the bench one in `tests/test_esp_nodes.py`, and run `uv run pytest -q
   tests/test_esp_nodes.py`.

## 4. A kind of entity Bento doesn't read yet

`number`, `select`, `button`, `cover` and `climate` aren't read yet. The list is `DOMAINS` in
[`agentos/espnodes.py`](../agentos/espnodes.py), and what can be set is `SETTABLE`. Adding one
touches the reader, the setter in `agentos/devio.py`, the simulator and the tests, so open an
issue first with the board you want it for. We'll agree on how it should look to an agent before
you write it.

Before any PR, read [CONTRIBUTING.md](../CONTRIBUTING.md). It's short.
