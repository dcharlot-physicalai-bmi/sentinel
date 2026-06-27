"""Cross-band corroboration. A declared event must sit on the manifold — be
supported by orthogonal bands within physical tolerance — or it escalates as
spoof-suspected rather than as a clean event. Also implements the inversion:
as trusted bands in a zone drop, the corroboration requirement RELAXES toward
catch-don't-miss (losing bands is itself evidence of a takedown), while a
single-band assertion that OTHER live bands contradict is flagged as spoof."""

import time
from dataclasses import dataclass, field


@dataclass
class ZoneEvidence:
    """Most-recent trusted reading per band in a zone, with age."""
    by_band: dict = field(default_factory=dict)   # band -> (value_dict, t_rx)

    def update(self, band, value, t_rx):
        self.by_band[band] = (value, t_rx)

    def fresh(self, band, max_age=2.0):
        v = self.by_band.get(band)
        if not v:
            return None
        value, t = v
        return value if (time.time() - t) <= max_age else None


# Which orthogonal bands can corroborate which event kind. Device-free presence
# bands (wifi CSI, mesh RTI, subghz, uwb, cband) all vote on body-state; camera
# adds pose; ble/uwb carry identity (who) for occupant assignment.
CORROBORATORS = {
    "fall":     ["uwb", "cband", "camera", "wifi", "mesh"],   # mmwave primary
    "vitals":   ["cband", "wifi"],                             # mmwave primary; cband through-wall, wifi coarse
    "presence": ["mmwave", "uwb", "cband", "camera", "wifi", "mesh", "subghz"],
    "immobile": ["mmwave", "uwb", "cband", "wifi", "mesh", "subghz"],
}

IDENTITY_BANDS = ["ble", "uwb"]   # answer "who", assigned to occupant tracks

# A contradiction only flags spoof if a band of at least this trust says "empty"
# while the primary fired. Below it, the band may SUPPORT but never VETO — a
# jammable wifi/mesh/subghz reading must not cause a false negative.
SPOOF_VETO_TRUST = 0.8


def on_manifold(kind, primary_band, zone_ev, trusted_weights):
    """trusted_weights: {band: trust_weight} for live bands in the zone.
    Returns (ok, support, contradiction).
      ok=False (spoof-suspected) ONLY when a HIGH-trust band (>= SPOOF_VETO_TRUST)
        actively contradicts and support is weaker — a forgeable band cannot veto.
      ok=True when corroborated, OR when no live corroborators remain (thinning
        manifold relaxes the bar toward catch-don't-miss)."""
    wanted = [b for b in CORROBORATORS.get(kind, []) if b != primary_band]
    live = [b for b in wanted if b in trusted_weights]

    support, contra = [], []
    support_w = contra_w = 0.0
    veto_w = 0.0   # strongest single contradicting band's trust
    for b in live:
        v = zone_ev.fresh(b)
        if v is None:
            continue
        w = trusted_weights[b]
        present = v.get("occupancy", v.get("presence", 0))
        if present:
            support.append(b); support_w += w
        else:
            contra.append(b); contra_w += w
            veto_w = max(veto_w, w)

    # spoof only if a high-trust band contradicts and outweighs support
    if veto_w >= SPOOF_VETO_TRUST and contra_w > support_w:
        return False, support, contra

    # no live corroborators at all -> do NOT block (bands lost = lowered bar)
    if not live:
        return True, support, contra

    return True, support, contra
