"""Event state machine, per zone (v0: one occupant per zone; per-identity tracks
are a later add). Consumes ONLY trust-gated, weighted, manifold-checked evidence.

Two-stage fall (candidate -> conjunction-confirm) gives both speed and low false
rate. Immobility uses an escalation ladder so stillness alone never alarms.
Error budget is INVERTED vs intruder security: over-fire, let recovery / human
self-cancel be the false-positive filter, because a missed event is fatal."""

import time
from enum import Enum
from dataclasses import dataclass, field


class S(Enum):
    EMPTY = "empty"
    ACTIVE = "active"
    FALL_CANDIDATE = "fall_candidate"
    FALL_ALARM = "fall_alarm"
    IMMOBILE_WATCH = "immobile_watch"
    VITALS_ALERT = "vitals_alert"


# tuning (seconds) — deliberately catch-don't-miss
FALL_CONFIRM_WINDOW = 0.4     # candidate -> confirm corroboration window
FALL_RECOVERY = 8.0           # rises/moves again within this -> self-cancel
IMMOBILE_T1 = 120.0           # still this long -> watch
IMMOBILE_T2 = 300.0           # still + corroborated -> alarm
VEL_FALL = 1.2                # m/s downward transient threshold (candidate)
VEL_STILL = 0.05              # m/s -> considered motionless


@dataclass
class ZoneFSM:
    zone: str
    tier: str
    state: S = S.EMPTY
    t_state: float = field(default_factory=time.time)
    last_motion: float = 0.0
    on_floor: bool = False
    breathing_rpm: float = None
    cand_t: float = 0.0
    cand_band: str = ""

    def _to(self, s):
        if s != self.state:
            self.state, self.t_state = s, time.time()

    def feed(self, ev, manifold, trusted_bands, emit_alarm):
        """ev: normalized fused sample for this zone:
           {band, occupancy, velocity_mps, range_m, on_floor, breathing_rpm,
            kind?}  kind is a sensor-side discrete event if present."""
        now = time.time()
        band = ev.get("band", "")
        occ = ev.get("occupancy", ev.get("presence", 0))
        vel = ev.get("velocity_mps")
        if ev.get("breathing_rpm") is not None:
            self.breathing_rpm = ev["breathing_rpm"]
        if ev.get("on_floor") is not None:
            self.on_floor = ev["on_floor"]
        if vel is not None and vel > VEL_STILL:
            self.last_motion = now

        # ---- presence baseline ----
        if not occ and self.state in (S.EMPTY, S.ACTIVE):
            self._to(S.EMPTY)
            return
        if occ and self.state == S.EMPTY:
            self._to(S.ACTIVE)

        # ---- fall: stage 1 candidate ----
        fired = ev.get("kind") == "fall_candidate" or (vel is not None and vel >= VEL_FALL)
        if fired and self.state in (S.ACTIVE, S.IMMOBILE_WATCH):
            self._to(S.FALL_CANDIDATE)
            self.cand_t, self.cand_band = now, band

        # ---- fall: stage 2 conjunction-confirm ----
        if self.state == S.FALL_CANDIDATE:
            still = vel is not None and vel < VEL_STILL
            if (now - self.cand_t) <= FALL_CONFIRM_WINDOW:
                if still and self.on_floor:
                    ok, support, contra = manifold("fall", self.cand_band, trusted_bands)
                    self._to(S.FALL_ALARM)
                    emit_alarm(dict(zone=self.zone, event="fall_confirmed",
                                    on_manifold=ok, support=support,
                                    contradiction=contra,
                                    action="dispatch" if ok else "investigate_spoof"))
            else:
                # window expired without prone+still -> was a fast sit, not a fall
                self._to(S.ACTIVE)

        # ---- fall recovery self-cancel ----
        # recovery = NEW motion after we entered the alarm AND they're off the
        # floor again. Motion from the fall itself (last_motion < t_state) does
        # not count, or the alarm would cancel itself instantly.
        if self.state == S.FALL_ALARM:
            got_up = (self.last_motion > self.t_state) and (not self.on_floor)
            if got_up and (now - self.t_state) < FALL_RECOVERY:
                emit_alarm(dict(zone=self.zone, event="fall_recovered",
                                action="cancel"))
                self._to(S.ACTIVE)

        # ---- immobility ladder ----
        still_for = now - self.last_motion
        if self.state in (S.ACTIVE, S.IMMOBILE_WATCH) and occ:
            if still_for > IMMOBILE_T1:
                self._to(S.IMMOBILE_WATCH)
            rung_alarm = (still_for > IMMOBILE_T2 and
                          (self.on_floor or self._vitals_abnormal()))
            if rung_alarm:
                ok, support, contra = manifold("immobile", band, trusted_bands)
                emit_alarm(dict(zone=self.zone, event="prolonged_immobility",
                                on_floor=self.on_floor,
                                vitals_abnormal=self._vitals_abnormal(),
                                on_manifold=ok, action="check_now"))

        # ---- vitals: only an event if presence persists (else they left) ----
        if occ and self._vitals_abnormal():
            ok, support, contra = manifold("vitals", band, trusted_bands)
            if self.state != S.VITALS_ALERT:
                self._to(S.VITALS_ALERT)
                emit_alarm(dict(zone=self.zone, event="abnormal_breathing",
                                rpm=self.breathing_rpm, on_manifold=ok,
                                action="check_now"))

    def _vitals_abnormal(self):
        r = self.breathing_rpm
        if r is None:
            return False
        # Layer-1 invariant bounds (never adapted): apnea / tachypnea
        return r < 6 or r > 28
