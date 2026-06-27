<div align="center">

# Sentinel

**A sensing fabric you can't spoof.**

*Multiband RF + optical sensing-fabric fusion: trust-weighted cross-band corroboration, fail-loud faulting, and a per-zone event state machine. The bands are not equal, and the code knows it.*

[![Charlot Lab](https://img.shields.io/badge/Charlot_Lab-Physical_AI_%40_BMI-cfaa5b?style=flat-square)](https://labs.physicalai-bmi.org/charlot)
[![Topic](https://img.shields.io/badge/research-Spatial_RF-46e0c0?style=flat-square)](https://physicalai-bmi.org/research/charlot-lab#topic-rf)
[![Python](https://img.shields.io/badge/Python-v0_skeleton-cfaa5b?style=flat-square&logo=python&logoColor=white)](#run)
[![License](https://img.shields.io/badge/license-MIT-46e0c0?style=flat-square)](LICENSE)

</div>

---

Sentinel is the research effort behind the Charlot Lab's **[Spatial RF](https://physicalai-bmi.org/research/charlot-lab#topic-rf)** topic. The cheapest way to spoof a sensor is to attack one band — so sense across all of them, and weight each by how hard it is to forge.

It ingests the full deliberate band set — mmWave (60 GHz vitals/fall), C-band (through-wall coherent), UWB (authenticated cm-ranging), Wi-Fi CSI (device-free motion/presence), BLE (identity + ranging), Zigbee/Thread mesh RTI (tomographic shadow), sub-GHz (coarse penetrating perimeter), and camera (pose/identity, non-private rooms) — over MQTT. It runs a fail-loud trust gate, a **trust-weighted** cross-band manifold check, and a per-zone event state machine (fall, immobility, abnormal breathing). Edge-local: the alarm decision is made on the node; any cloud uplink is advisory only.

## Why trust is asymmetric

The bands are not equal, and `band_trust` in `config/nodes.yaml` weights each by how hard it is to forge. Owned keyed-coherent (mmWave, C-band) and authenticated-ranging (UWB) are **high**; passive ambient-readout bands (Wi-Fi CSI, mesh RTI, sub-GHz, BLE) are **low**. The asymmetry is load-bearing:

- A low-trust band may **add** corroboration but can **never veto** a real event — a jammed Wi-Fi reading must not cause a missed fall.
- Only a **high-trust** band contradicting a primary flags **spoof**.

This is the **product-not-sum** property: defeating the fabric requires forging a *jointly consistent* signature across 60 GHz + ~5 GHz + 6.5 GHz UWB + 2.4/5/6 GHz Wi-Fi/BLE/mesh + 900 MHz **simultaneously** — physically incompatible attacks across the whole spectrum. And **silence is a fault, not a gap**: a dead or jammed node lowers the bar rather than blinding the system.

```
nodes ──MQTT──>  ingest ──> trust gate (fail-loud) ──> per-zone evidence
                                                          │
                                              manifold corroboration
                                                          │
                                                  event state machine
                                                          │
                                            fusion/alarm   fusion/fault
```

## Demo

[`demo/sentinel.html`](demo/sentinel.html) — a self-contained interactive visualization: six bands ringing a subject, cycling through monitoring → fall → spoof → fault, each band agreeing, contradicting, dead, or idle, with the fused verdict. Open it in any browser, or see it live on the lab page: **[Spatial RF ↗](https://physicalai-bmi.org/research/charlot-lab#topic-rf)**.

## Layout

- `TOPICS.md` — MQTT topic + payload schema
- `config/nodes.yaml` — node registry (which bands cover which zone, per-band trust, heartbeat cadence)
- `fusion/trust.py` — fail-loud heartbeat watchdog: DEAD / SUSPECT / OK; epoch-frozen detection (replayed transmitter == fault)
- `fusion/manifold.py` — cross-band corroboration; contradiction by a live band = off-manifold = spoof; lost bands relax the bar
- `fusion/events.py` — per-zone FSM; 2-stage fall (candidate → confirm), immobility ladder, vitals-only-if-present
- `fusion/main.py` — MQTT wiring + 10 Hz tick loop
- `esphome/` — per-node ESPHome config (Seeed mmWave → MQTT)
- `selftest.py` — exercises the whole chain with no broker and no hardware
- `docs/figures/` — architecture diagrams (co-located node, three-tier, multistatic geometry, timing plane, compression cascade)

## Run

```bash
pip install paho-mqtt pyyaml

# verify the fusion logic offline (no broker, no hardware):
python selftest.py

# run live against a broker:
docker run -p 1883:1883 eclipse-mosquitto
python -m fusion.main
```

## What v0 proves — and what it does not

**Proves:** multi-band detection + corroboration + fail-loud faulting all work end to end.

**Does not:** the spoof-resistance is only as strong as time alignment. Over Wi-Fi/MQTT (~10–100 ms jitter) the manifold catches crude contradiction but **not** a time-aligned coherent injection. The product-not-sum spoof property requires the production move: wired/PoE nodes + PTP sub-ms sync + keyed coherent waveforms (the `key_epoch` field is the v0 placeholder for that key schedule). **Do not demo v0 and claim spoof-proof.**

## Tuning posture

Inverted error budget: a false negative is a dead customer. Thresholds in `events.py` are set to over-fire; recovery self-cancel plus a human "check now" prompt are the false-positive filter. Per-person baselines (not in v0) are the real FP-reduction layer — added after the fabric is proven.

## Status

Sentinel is an active **research effort** of [the Charlot Lab](https://labs.physicalai-bmi.org/charlot) at the Institute for Physical AI, Bailey Military Institute — the research effort behind the lab's **Spatial RF** topic. v0 is a fusion skeleton; interfaces will change.

## Links

- **Research topic** — https://physicalai-bmi.org/research/charlot-lab#topic-rf
- **The Charlot Lab** — https://labs.physicalai-bmi.org/charlot
- **Institute for Physical AI** — https://physicalai-bmi.org

---

<div align="center">
<sub>The Charlot Lab · Institute for Physical AI · Bailey Military Institute</sub>
</div>
