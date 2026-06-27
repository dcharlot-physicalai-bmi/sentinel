"""Offline check: exercise trust gate + manifold + FSM with no broker, so the
logic is verified before any hardware exists. Simulates a fall in the bathroom
with mmwave primary + uwb/cband corroboration, then a node-death fault."""

import sys, time, yaml
sys.path.insert(0, ".")
from fusion.trust import TrustGate, Trust
from fusion.manifold import ZoneEvidence, on_manifold
from fusion.events import ZoneFSM

reg = yaml.safe_load(open("config/nodes.yaml"))
alarms, faults = [], []
gate = TrustGate(reg, on_fault=lambda n, k, z: faults.append((n, k, z)))

# bring bathroom + shower nodes alive (now incl. wifi)
now = time.time()
for nid in ["MW-03", "MW-04", "UW-02", "CB-03", "WF-02"]:
    gate.on_heartbeat(nid, {"seq": 1, "key_epoch": 1})
gate.tick()
print("trusted bands in bathroom:", gate.trusted_weights_in_zone("bathroom"))
print("trusted bands in shower:", gate.trusted_weights_in_zone("shower"))

# build evidence + fsm for shower zone (MW-04 lives there)
ze = ZoneEvidence()
fsm = ZoneFSM(zone="shower", tier="critical")
def check(kind, primary, trusted):
    return on_manifold(kind, primary, ze, trusted)
def emit(d): alarms.append(d); print("  ALARM ->", d["event"], d.get("action"))

trusted = {**gate.trusted_weights_in_zone("shower"),
           **gate.trusted_weights_in_zone("bathroom")}

# corroborating bands say a body is present in the zone
ze.update("uwb",   {"presence": 1}, time.time())
ze.update("cband", {"presence": 1}, time.time())

print("\n-- fall sequence --")
fsm.feed({"band": "mmwave", "occupancy": 1, "velocity_mps": 0.6}, check, trusted, emit)  # active
fsm.feed({"band": "mmwave", "occupancy": 1, "velocity_mps": 1.8, "on_floor": False}, check, trusted, emit)  # candidate
print("  state after candidate:", fsm.state.value)
fsm.feed({"band": "mmwave", "occupancy": 1, "velocity_mps": 0.0, "on_floor": True}, check, trusted, emit)  # confirm
print("  state after confirm:", fsm.state.value)

print("\n-- spoof case: HIGH-trust bands (uwb,cband) say empty --")
ze.update("uwb",   {"presence": 0}, time.time())
ze.update("cband", {"presence": 0}, time.time())
fsm2 = ZoneFSM(zone="shower", tier="critical")
fsm2.feed({"band": "mmwave", "occupancy": 1, "velocity_mps": 1.8}, check, trusted, emit)
fsm2.feed({"band": "mmwave", "occupancy": 1, "velocity_mps": 0.0, "on_floor": True}, check, trusted, emit)
last = alarms[-1]
print("  on_manifold:", last["on_manifold"], "| action:", last["action"])

print("\n-- low-trust-cant-veto: only wifi (0.5) says empty, real fall --")
ze2 = ZoneEvidence()
ze2.update("wifi", {"presence": 0}, time.time())   # jammable band contradicts
def check2(kind, primary, trusted):
    return on_manifold(kind, primary, ze2, trusted)
fsm3 = ZoneFSM(zone="shower", tier="critical")
fsm3.feed({"band": "mmwave", "occupancy": 1, "velocity_mps": 1.8}, check2, trusted, emit)
fsm3.feed({"band": "mmwave", "occupancy": 1, "velocity_mps": 0.0, "on_floor": True}, check2, trusted, emit)
veto_test = alarms[-1]
print("  on_manifold:", veto_test["on_manifold"], "| action:", veto_test["action"],
      "(wifi alone must NOT veto)")

print("\n-- fail-loud: kill MW-04 heartbeat, advance time --")
gate.nodes["MW-04"].last_hb -= 10  # simulate 10s since last hb
gate.tick()
print("  MW-04 trust:", gate.nodes["MW-04"].trust.value)
print("  faults emitted:", faults)

print("\n-- epoch-frozen liveness fault (packets arrive but epoch stuck) --")
g2 = TrustGate(reg, on_fault=lambda n, k, z: faults.append((n, k, z)))
for _ in range(5):
    g2.on_heartbeat("CB-03", {"seq": 5, "key_epoch": 7})  # epoch never advances
    g2.nodes["CB-03"].epoch_frozen_since -= 5  # age the freeze
g2.tick()
print("  CB-03 trust:", g2.nodes["CB-03"].trust.value)

assert any(a["event"] == "fall_confirmed" and a["on_manifold"] for a in alarms), "corroborated fall missing"
assert any(a.get("on_manifold") is False for a in alarms), "spoof case not flagged"
assert veto_test["on_manifold"] is True, "low-trust wifi wrongly vetoed a real fall"
assert ("MW-04", "dead", "shower") in faults, "death fault missing"
print("\nALL CHECKS PASSED")
