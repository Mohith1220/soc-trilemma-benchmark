"""SessionManager: wires together SeedEngine, KillChain, SOCGrader, and PrettyPrinter."""
from __future__ import annotations

import asyncio
import random
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException

from app.kill_chain import KillChain
from app.models import (
    ACTION_COSTS,
    Action,
    ActionType,
    Alert,
    DPIEntry,
    DPISnapshot,
    DPITemplate,
    KillChainStage,
    Observation,
    TaskConfig,
)
from app.pretty_printer import PrettyPrinter
from app.seed_engine import RoleAssignment, SeedEngine
from app.soc_grader import SOCGrader

# ---------------------------------------------------------------------------
# Fixed 12-IP pool
# ---------------------------------------------------------------------------
_IP_POOL: list[str] = [f"10.0.0.{i}" for i in range(1, 13)]
_IP_POOL_SET: frozenset[str] = frozenset(_IP_POOL)

_TIER_PENALTY = {
    "CRITICAL": 0.15,
    "INTERNAL": 0.05,
    "LOW": 0.01,
}

_MASKED_PAYLOAD = "Standard Traffic"
_MALICIOUS_PAYLOAD = "MALICIOUS SIGNATURE DETECTED"

# Maximum concurrent sessions — LRU evicts oldest when exceeded
_MAX_SESSIONS = 100


def _stage_for_tick(tick: int) -> KillChainStage:
    if tick <= 20:
        return KillChainStage.Recon
    if tick <= 40:
        return KillChainStage.LateralMovement
    return KillChainStage.Exfiltration


def _assign_tiers(rng: random.Random, ips: list[str]) -> dict[str, str]:
    labels = ["CRITICAL"] * 2 + ["INTERNAL"] * 4 + ["LOW"] * 6
    rng.shuffle(labels)
    return dict(zip(ips, labels))


def _build_dpi_snapshot(
    stage: KillChainStage,
    attacker_ip: str,
    decoy_ips: list[str],
    all_ips: list[str],
    queried_ips: set[str],
) -> DPISnapshot:
    entries: list[DPIEntry] = []
    for ip in all_ips:
        if ip == attacker_ip and ip in queried_ips:
            payload = _MALICIOUS_PAYLOAD
        else:
            payload = _MASKED_PAYLOAD
        entries.append(DPIEntry(
            src_ip=ip,
            dst_ip="10.0.0.254",
            protocol="TCP",
            payload_summary=payload,
            flags=["SYN"] if ip == attacker_ip else [],
        ))
    return DPISnapshot(
        stage=stage,
        entries=entries,
        attacker_ip=attacker_ip,
        decoy_ips=decoy_ips,
    )


@dataclass
class _SessionState:
    kill_chain: KillChain
    soc_grader: SOCGrader
    seed: int
    attacker_ip: str
    backup_attacker_ip: str
    decoy_ips: list[str]
    all_ips: list[str]
    ip_tiers: dict[str, str]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    has_pivoted: bool = False
    step_count: int = 0
    done: bool = False
    alerts: list[Alert] = field(default_factory=list)
    queried_ips: set[str] = field(default_factory=set)
    suspended_at: Optional[float] = None


class SessionManager:
    def __init__(self, task_config: TaskConfig) -> None:
        self._task_config = task_config
        # OrderedDict gives us LRU eviction: move_to_end on access, popitem(last=False) to evict
        self._sessions: OrderedDict[str, _SessionState] = OrderedDict()
        self._seed_engine = SeedEngine()
        self._printer = PrettyPrinter()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_or_reset(self, session_id: str, seed: int) -> Observation:
        rng = random.Random(seed)
        pool = list(_IP_POOL)
        rng.shuffle(pool)

        attacker_ip = pool[0]
        backup_attacker_ip = pool[1]
        decoy_ips = pool[1:4]
        all_ips = pool
        ip_tiers = _assign_tiers(rng, all_ips)

        template = DPITemplate(stage=KillChainStage.Recon, entries=[], ip_pool=pool)
        role = RoleAssignment(attacker_ip=attacker_ip, decoy_ips=decoy_ips)
        kc = KillChain()
        kc.load_stage_template(template, role)

        grader = SOCGrader(
            sla_penalty_rate=self._task_config.sla_penalty_rate,
            ip_tiers=ip_tiers,
        )

        state = _SessionState(
            kill_chain=kc,
            soc_grader=grader,
            seed=seed,
            attacker_ip=attacker_ip,
            backup_attacker_ip=backup_attacker_ip,
            decoy_ips=decoy_ips,
            all_ips=all_ips,
            ip_tiers=ip_tiers,
        )

        # LRU: evict oldest session if at capacity
        if session_id in self._sessions:
            del self._sessions[session_id]
        elif len(self._sessions) >= _MAX_SESSIONS:
            self._sessions.popitem(last=False)  # evict LRU

        self._sessions[session_id] = state
        return self._build_observation(state, done=False)

    def step(self, session_id: str, action: Action) -> Observation:
        """Synchronous step — wraps _step_inner without async lock for HTTP endpoints."""
        state = self._get_or_404(session_id)
        # Mark session as recently used (LRU)
        self._sessions.move_to_end(session_id)
        return self._step_inner(state, action)

    async def async_step(self, session_id: str, action: Action) -> Observation:
        """Async step with per-session lock — used by WebSocket endpoint."""
        state = self._get_or_404(session_id)
        self._sessions.move_to_end(session_id)
        async with state.lock:
            return self._step_inner(state, action)

    def _step_inner(self, state: _SessionState, action: Action) -> Observation:
        # Guard: reject actions on completed episodes
        if state.done:
            raise HTTPException(
                status_code=400,
                detail="Episode is already done. Call /reset to start a new episode.",
            )

        # Guard: reject IPs not in this session's pool
        if action.target_ip not in _IP_POOL_SET:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"target_ip '{action.target_ip}' is not in the valid IP pool. "
                    f"Valid IPs: {sorted(_IP_POOL_SET)}"
                ),
            )

        tick_cost = ACTION_COSTS[action.action_type]
        current_tick = state.kill_chain.tick

        # 1. SLA bleed
        state.soc_grader.apply_tick_penalties(tick_cost)

        # 2. query_dpi + adversarial pivot
        if action.action_type == ActionType.QueryDPI:
            state.queried_ips.add(action.target_ip)
            state.alerts.append(Alert(
                message=f"DPI query completed for {action.target_ip}",
                severity="info",
                tick=current_tick + tick_cost,
            ))
            if (
                not state.has_pivoted
                and action.target_ip == state.attacker_ip
                and state.kill_chain.stage == KillChainStage.LateralMovement
            ):
                old_attacker = state.attacker_ip
                state.attacker_ip = state.backup_attacker_ip
                state.has_pivoted = True
                state.alerts.append(Alert(
                    message=(
                        f"PIVOT DETECTED — attacker moved from {old_attacker} "
                        f"to {state.attacker_ip}"
                    ),
                    severity="critical",
                    tick=current_tick + tick_cost,
                ))

        # 3. Grade action
        grade = state.soc_grader.grade_action(action, state.attacker_ip, current_tick)

        if grade.outage_created:
            tier = state.ip_tiers.get(action.target_ip, "LOW")
            state.alerts.append(Alert(
                message=(
                    f"[{tier}] Business outage: {action.target_ip} — "
                    f"SLA bleed {_TIER_PENALTY[tier]}/tick"
                ),
                severity="warning",
                tick=current_tick + tick_cost,
            ))
        if grade.outage_resolved:
            state.alerts.append(Alert(
                message=f"Outage resolved for {action.target_ip}",
                severity="info",
                tick=current_tick + tick_cost,
            ))

        # 4. Advance tick
        state.kill_chain.advance_tick(tick_cost)
        new_tick = state.kill_chain.tick

        # 5. Stage sync
        new_stage = _stage_for_tick(new_tick)
        if new_stage != state.kill_chain.stage:
            state.kill_chain.stage = new_stage
            state.kill_chain.stage_tick_start = new_tick
            state.alerts.append(Alert(
                message=f"Kill chain advanced to {new_stage.value}",
                severity="critical",
                tick=new_tick,
            ))

        # 6. Termination
        correct_block = (
            action.action_type == ActionType.BlockIP
            and action.target_ip == state.attacker_ip
        )
        state.step_count += 1
        done = (
            correct_block
            or new_tick > 60
            or state.step_count >= self._task_config.max_steps
        )

        if done and not correct_block and new_tick > 60:
            state.soc_grader.survival_score = max(
                0.0, state.soc_grader.survival_score - 1.0
            )
            state.alerts.append(Alert(
                message="Attacker exfiltrated data — mission failed",
                severity="critical",
                tick=new_tick,
            ))

        state.done = done
        return self._build_observation(state, done=done)

    def get_state(self, session_id: str) -> Observation:
        state = self._get_or_404(session_id)
        self._sessions.move_to_end(session_id)
        return self._build_observation(state, done=state.done)

    def cleanup_expired_sessions(self) -> None:
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if s.suspended_at is not None and (now - s.suspended_at) > 30
        ]
        for sid in expired:
            del self._sessions[sid]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_or_404(self, session_id: str) -> _SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return state

    def _build_observation(self, state: _SessionState, *, done: bool) -> Observation:
        snapshot = _build_dpi_snapshot(
            stage=state.kill_chain.stage,
            attacker_ip=state.attacker_ip,
            decoy_ips=state.decoy_ips,
            all_ips=state.all_ips,
            queried_ips=state.queried_ips,
        )
        state.kill_chain.dpi_snapshot = snapshot

        obs = Observation(
            stage=state.kill_chain.stage,
            dpi_data=snapshot,
            alerts=list(state.alerts),
            survival_score=state.soc_grader.survival_score,
            tick=state.kill_chain.tick,
            done=done,
            dom="",
        )
        obs.dom = self._printer.render_dashboard(obs)
        return obs
