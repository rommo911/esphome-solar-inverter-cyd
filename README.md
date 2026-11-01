# CYD inverter controller

Standalone controller for an Axpert VMIII-4000 (24 V, PI30) on an ESP32-2432S028R "Cheap Yellow
Display" (2-USB revision, ILI9342). Works without Home Assistant; HA can connect later through the
native API (all settings and the useful readings are exposed, internals are not).

- `inverter-cyd.yaml`: the ESPHome config (the only file that goes on the board)
- `CYD_HANDOFF.md`: background, hardware, rules and the agreed design
- `docs/screens/`: rendered previews of every screen page

## Rules (from the owner)
Back up before changing, validate with `esphome config`, compile only with the owner's OK, never
flash from here (the owner flashes `firmware/inverter-cyd.factory.bin` at web.esphome.io).

## Workflow
The ESPHome container (`compose.yaml`) uses `./config` as `/config`; copy the YAML there to build:

    docker cp inverter-cyd.yaml esphome:/config/inverter-cyd.yaml
    docker exec esphome esphome config /config/inverter-cyd.yaml
    docker exec -e ESPHOME_ESP_IDF_PREFIX=/config/.esphome/idf esphome esphome compile /config/inverter-cyd.yaml

(Pass `ESPHOME_ESP_IDF_PREFIX` exactly as above, or CLI and dashboard builds break each other.)

Generated parts of the YAML (edit the tool, not the YAML):

| Part | Source | Apply |
|---|---|---|
| `number:` / `switch:`, `ui_sync_all`, `restore_defaults` | `tools/cyd_settings.py` | `python3 tools/cyd_settings_apply.py inverter-cyd.yaml` |
| `lvgl:` section, `ui_refresh_values` | `tools/cyd_ui.py` | run `cyd_ui.py check/render/yaml/script` in the container, then `tools/cyd_ui_inject.py` |

`cyd_ui.py check` verifies against LVGL's real Montserrat glyph widths that no text overlaps or
leaves the screen; `render` draws PNG previews.

## Simulation
`tools/sim/run.sh` extracts the controller's lambdas verbatim from the YAML, compiles them (g++ in the
ESPHome container) against a simulated house, battery, PV, grid and inverter, runs every scenario
and checks the results (`tools/sim/check.py`). Run it after any change to the control logic:

    cd tools/sim && ./run.sh ../../inverter-cyd.yaml results
