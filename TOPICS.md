# MQTT topic schema (v0)

Broker: mosquitto on the fusion node (FUS-01). Everything is line-rate JSON.
All timestamps are `t_src` (ms epoch, sensor-stamped) AND re-stamped `t_rx` at
ingest. v0 fuses on `t_rx` (Wi-Fi jitter ~10-100ms); production uses `t_src`
once nodes share a PTP clock.

## Inbound (nodes -> fusion)

```
sensor/<node_id>/meta            retained, QoS1   capabilities, room, zone (on connect)
sensor/<node_id>/heartbeat       QoS0, periodic   liveness proof  -> trust gate
sensor/<node_id>/telemetry       QoS0, streaming  continuous scalars (velocity, vitals, occupancy)
sensor/<node_id>/event           QoS1             discrete sensor-side event (fall, presence edge)
```

### payloads

meta (retained):
```json
{"node_id":"MW-01","room":"primary_br","zone":"bedside","band":"mmwave",
 "caps":["fall","presence"],"hb_interval_ms":2000}
```

heartbeat:
```json
{"node_id":"MW-01","t_src":1718380000123,"seq":4412,"key_epoch":91833,"rssi":-52}
```
`key_epoch` is the current keyed-waveform epoch (production). In v0 it is a
monotonic counter; a frozen/stale epoch is treated as a liveness fault.

telemetry:
```json
{"node_id":"MW-09","t_src":...,"band":"mmwave",
 "occupancy":1,"velocity_mps":1.8,"range_m":2.3}
```
vitals telemetry (MR60BHA2 / C-band):
```json
{"node_id":"MW-02","t_src":...,"breathing_rpm":14.2,"heart_bpm":68,"presence":1}
```

wifi CSI telemetry (passive, device-free):
```json
{"node_id":"WF-02","t_src":...,"band":"wifi","presence":1,"motion":0.3,"breathing_coarse":15}
```
ble (identity + ranging — answers "who/where", feeds occupant assignment):
```json
{"node_id":"BL-01","t_src":...,"band":"ble","presence":1,"range_m":1.4,
 "device":"resident_watch","secure_range":true}
```
mesh RTI (zigbee/thread link-graph shadow — the GRAPH senses, payload is the
reconstructed per-zone occupancy from the link matrix):
```json
{"node_id":"ME-01","t_src":...,"band":"mesh","presence":1,"links_shadowed":7}
```
subghz (900 MHz coarse penetrating presence / perimeter):
```json
{"node_id":"SG-01","t_src":...,"band":"subghz","presence":1,"perimeter":0}
```

event:
```json
{"node_id":"MW-03","t_src":...,"band":"mmwave","kind":"fall_candidate","conf":0.7}
```

## Outbound (fusion -> world)

```
fusion/zone/<zone>/state    retained   per-zone fused state
fusion/alarm                QoS1       declared events needing action
fusion/fault                QoS1       fail-loud: dead/jammed/spoof-suspected node
```

alarm:
```json
{"zone":"bathroom","occupant":"resident","event":"fall_confirmed",
 "t":...,"bands":["mmwave","uwb","cband"],"on_manifold":true,"action":"check_now"}
```

fault (this is the product's spine — silence is a fault):
```json
{"node_id":"MW-04","kind":"dead","since":...,"zone":"bathroom",
 "effect":"bathroom coverage degraded; threshold lowered"}
```
