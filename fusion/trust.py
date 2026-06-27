"""Per-modality trust gate. Runs first, every tick. Answers 'do I believe this
node right now' BEFORE any event logic consumes its evidence. The cardinal rule:
a dead or spoof-suspected node must NEVER read as 'all clear' — its silence is a
fault that lowers the zone's alarm threshold, not weak negative evidence."""

import time
from dataclasses import dataclass, field
from enum import Enum


class Trust(Enum):
    OK = "ok"
    SUSPECT = "spoof_suspected"   # injection: correlates wrong / off-manifold
    DEAD = "dead"                 # jam/fail: heartbeat missing or epoch frozen


@dataclass
class NodeState:
    node_id: str
    band: str
    zone: str
    hb_ms: int
    hb_grace: float
    last_hb: float = 0.0
    last_seq: int = -1
    last_key_epoch: int = -1
    epoch_frozen_since: float = 0.0
    spoof_flag: bool = False
    trust: Trust = Trust.DEAD          # start DEAD until first heartbeat proves life
    weight: float = 0.0                # evidence weight in [0,1]


class TrustGate:
    def __init__(self, registry, on_fault):
        self.nodes = {}
        self.on_fault = on_fault       # callback(node_id, kind, zone) -> publish fault
        self.band_trust = registry.get("band_trust", {})
        d = registry["defaults"]["hb_grace"]
        for n in registry["nodes"]:
            self.nodes[n["id"]] = NodeState(
                node_id=n["id"], band=n["band"], zone=n["zone"],
                hb_ms=n["hb_ms"], hb_grace=registry.get("hb_grace", d))

    def on_heartbeat(self, node_id, msg):
        ns = self.nodes.get(node_id)
        if not ns:
            return
        now = time.time()
        ns.last_hb = now
        # frozen key_epoch == a replayed/stuck transmitter -> liveness fault even
        # though packets arrive. Real life advances the epoch.
        ke = msg.get("key_epoch", -1)
        if ke == ns.last_key_epoch and ke != -1:
            if ns.epoch_frozen_since == 0.0:
                ns.epoch_frozen_since = now
        else:
            ns.epoch_frozen_since = 0.0
        ns.last_key_epoch = ke
        ns.last_seq = msg.get("seq", ns.last_seq)

    def flag_spoof(self, node_id, on=True):
        if node_id in self.nodes:
            self.nodes[node_id].spoof_flag = on

    def tick(self):
        """Recompute trust for every node. Emit faults on transitions into a bad
        state. Returns {node_id: NodeState}."""
        now = time.time()
        for ns in self.nodes.values():
            prev = ns.trust
            dead_after = (ns.hb_ms / 1000.0) * ns.hb_grace
            epoch_dead = ns.epoch_frozen_since and (now - ns.epoch_frozen_since) > dead_after

            if (now - ns.last_hb) > dead_after or epoch_dead:
                ns.trust, ns.weight = Trust.DEAD, 0.0
            elif ns.spoof_flag:
                ns.trust, ns.weight = Trust.SUSPECT, 0.0
            else:
                ns.trust = Trust.OK
                ns.weight = self.band_trust.get(ns.band, 1.0)

            if ns.trust != prev and ns.trust != Trust.OK:
                kind = "epoch_frozen" if epoch_dead else ns.trust.value
                self.on_fault(ns.node_id, kind, ns.zone)
        return self.nodes

    def trusted_in_zone(self, zone):
        """Bands currently trustworthy in a zone — drives manifold corroboration
        and the 'thinning manifold lowers threshold' inversion."""
        return {ns.band for ns in self.nodes.values()
                if ns.zone == zone and ns.trust == Trust.OK}

    def trusted_weights_in_zone(self, zone):
        """{band: trust_weight} for live bands in a zone. The manifold weights
        corroboration AND the spoof veto by these — a low-trust band can support
        but cannot veto a real event."""
        return {ns.band: ns.weight for ns in self.nodes.values()
                if ns.zone == zone and ns.trust == Trust.OK}
