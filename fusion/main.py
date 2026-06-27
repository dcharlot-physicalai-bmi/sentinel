"""Fusion service entrypoint. Wires: MQTT ingest -> trust gate (fail-loud) ->
per-zone evidence -> event FSM (manifold-gated) -> alarm/fault out. Runs a fixed
tick (the 60 Hz fused grid in production; 10 Hz is plenty for v0 demo).

Run:  python -m fusion.main   (needs: paho-mqtt, pyyaml, a mosquitto broker)
"""

import json, time, threading, yaml
import paho.mqtt.client as mqtt

from .trust import TrustGate, Trust
from .manifold import ZoneEvidence, on_manifold
from .events import ZoneFSM

TICK_HZ = 10
REGISTRY = yaml.safe_load(open("config/nodes.yaml"))


class Fusion:
    def __init__(self):
        self.cli = mqtt.Client(client_id="fusion")
        self.cli.on_connect = self._on_connect
        self.cli.on_message = self._on_message
        self.gate = TrustGate(REGISTRY, on_fault=self._publish_fault)
        self.zone_ev = {z: ZoneEvidence() for z in REGISTRY["zones"]}
        self.fsm = {z: ZoneFSM(zone=z, tier=REGISTRY["zones"][z]["tier"])
                    for z in REGISTRY["zones"]}
        self.node_zone = {n["id"]: n["zone"] for n in REGISTRY["nodes"]}
        self.node_band = {n["id"]: n["band"] for n in REGISTRY["nodes"]}
        self.lock = threading.Lock()

    # ---- MQTT ----
    def _on_connect(self, c, *_):
        c.subscribe("sensor/+/heartbeat", qos=0)
        c.subscribe("sensor/+/telemetry", qos=0)
        c.subscribe("sensor/+/event", qos=1)
        print("[fusion] subscribed")

    def _on_message(self, c, _u, m):
        try:
            payload = json.loads(m.payload)
        except Exception:
            return
        t_rx = time.time()
        parts = m.topic.split("/")
        node_id, kind = parts[1], parts[2]
        with self.lock:
            if kind == "heartbeat":
                self.gate.on_heartbeat(node_id, payload)
                return
            zone = self.node_zone.get(node_id)
            band = self.node_band.get(node_id)
            if zone is None:
                return
            payload["band"] = band
            # only trusted nodes feed evidence + baseline; spoof/dead are excluded
            if self.gate.nodes[node_id].trust == Trust.OK:
                self.zone_ev[zone].update(band, payload, t_rx)
                self._buffer(zone, payload)

    def _buffer(self, zone, payload):
        # stash latest sample per zone for the tick loop to consume
        self._pending.setdefault(zone, []).append(payload)

    # ---- alarm / fault out ----
    def _publish_alarm(self, d):
        d["t"] = int(time.time() * 1000)
        self.cli.publish("fusion/alarm", json.dumps(d), qos=1)
        print("[ALARM]", d)

    def _publish_fault(self, node_id, kind, zone):
        d = dict(node_id=node_id, kind=kind, zone=zone,
                 since=int(time.time() * 1000),
                 effect=f"{zone} coverage degraded; threshold lowered")
        self.cli.publish("fusion/fault", json.dumps(d), qos=1)
        print("[FAULT]", d)

    # ---- tick loop ----
    def _manifold_for(self, zone):
        def check(kind, primary_band, trusted_weights):
            return on_manifold(kind, primary_band, self.zone_ev[zone], trusted_weights)
        return check

    def run(self):
        self._pending = {}
        self.cli.connect("localhost", 1883, 60)
        self.cli.loop_start()
        period = 1.0 / TICK_HZ
        while True:
            t0 = time.time()
            with self.lock:
                self.gate.tick()                 # fail-loud first
                pending, self._pending = self._pending, {}
            for zone, samples in pending.items():
                trusted = self.gate.trusted_weights_in_zone(zone)
                check = self._manifold_for(zone)
                for s in samples:
                    self.fsm[zone].feed(s, check, trusted, self._publish_alarm)
            self._publish_zone_states()
            time.sleep(max(0, period - (time.time() - t0)))

    def _publish_zone_states(self):
        for z, fsm in self.fsm.items():
            self.cli.publish(f"fusion/zone/{z}/state",
                             json.dumps(dict(zone=z, state=fsm.state.value,
                                             bands=list(self.gate.trusted_in_zone(z)))),
                             qos=0, retain=True)


if __name__ == "__main__":
    Fusion().run()
