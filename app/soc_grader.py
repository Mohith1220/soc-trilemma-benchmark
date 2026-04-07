from __future__ import annotations

from app.models import Action, ActionType, BusinessOutage, GradeResult

# Tiered penalty rates per tick per blocked IP
_TIER_PENALTY: dict[str, float] = {
    "CRITICAL": 0.15,
    "INTERNAL": 0.05,
    "LOW": 0.01,
}


def _clamp(score: float) -> float:
    """
    Clamp score strictly inside (0,1) range required by OpenEnv.
    Prevents exact 0.0 and 1.0.
    """
    epsilon = 0.005
    return max(epsilon, min(1.0 - epsilon, score))


class SOCGrader:
    survival_score: float
    active_outages: list[BusinessOutage]
    sla_penalty_rate: float
    ip_tiers: dict[str, str]

    def __init__(
        self,
        sla_penalty_rate: float,
        ip_tiers: dict[str, str] | None = None,
    ) -> None:
        self.sla_penalty_rate = sla_penalty_rate
        self.ip_tiers = ip_tiers or {}
        self.survival_score = 0.995  # Start at ceiling to avoid exact 1.0
        self.active_outages = []

    def _penalty_for(self, target_ip: str) -> float:
        """Return per-tick penalty rate for given IP based on tier."""
        tier = self.ip_tiers.get(target_ip)
        if tier and tier in _TIER_PENALTY:
            return _TIER_PENALTY[tier]
        return self.sla_penalty_rate

    def grade_action(
        self, action: Action, attacker_ip: str, current_tick: int
    ) -> GradeResult:

        # BLOCK IP
        if action.action_type == ActionType.BlockIP:
            if action.target_ip == attacker_ip:
                self.survival_score = _clamp(self.survival_score + 0.2)
                return GradeResult(
                    reward=0.2,
                    outage_created=False,
                    outage_resolved=False,
                    survival_score=self.survival_score,
                )
            else:
                # Incorrect block → create outage
                penalty_rate = self._penalty_for(action.target_ip)

                outage = BusinessOutage(
                    target_ip=action.target_ip,
                    created_at_tick=current_tick,
                    penalty_per_tick=penalty_rate,
                )
                self.active_outages.append(outage)

                # apply shock penalty
                self.survival_score = _clamp(self.survival_score - 0.1)

                return GradeResult(
                    reward=-0.1,
                    outage_created=True,
                    outage_resolved=False,
                    survival_score=self.survival_score,
                )

        # RESOLVE OUTAGE
        if action.action_type == ActionType.ResolveOutage:
            resolved = self.resolve_outage(action.target_ip)
            return GradeResult(
                reward=0.0,
                outage_created=False,
                outage_resolved=resolved,
                survival_score=self.survival_score,
            )

        # QueryDPI / Wait etc
        return GradeResult(
            reward=0.0,
            outage_created=False,
            outage_resolved=False,
            survival_score=self.survival_score,
        )

    def apply_tick_penalties(self, tick_cost: int) -> None:
        """Apply SLA bleed penalties for active outages."""
        penalty = sum(
            outage.penalty_per_tick * tick_cost for outage in self.active_outages
        )

        raw = self.survival_score - penalty
        self.survival_score = _clamp(raw)

    def resolve_outage(self, target_ip: str) -> bool:
        for i, outage in enumerate(self.active_outages):
            if outage.target_ip == target_ip:
                self.active_outages.pop(i)
                return True
        return False