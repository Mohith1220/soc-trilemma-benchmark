from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, field_serializer, field_validator


class KillChainStage(str, Enum):
    Recon = "Recon"
    LateralMovement = "Lateral_Movement"
    Exfiltration = "Exfiltration"


class ActionType(str, Enum):
    BlockIP = "block_ip"
    AllowIP = "allow_ip"
    IsolateHost = "isolate_host"
    ResolveOutage = "resolve_outage"
    QueryDPI = "query_dpi"
    Wait = "wait"


# Maps every ActionType to a positive integer tick cost
ACTION_COSTS: dict[ActionType, int] = {
    ActionType.BlockIP: 3,
    ActionType.AllowIP: 1,
    ActionType.IsolateHost: 5,
    ActionType.ResolveOutage: 3,
    ActionType.QueryDPI: 5,
    ActionType.Wait: 1,
}


class Action(BaseModel):
    action_type: ActionType
    target_ip: str
    session_id: str

    @field_validator("target_ip")
    @classmethod
    def validate_ipv4(cls, v: str) -> str:
        import ipaddress
        try:
            addr = ipaddress.ip_address(v)
            if not isinstance(addr, ipaddress.IPv4Address):
                raise ValueError("target_ip must be an IPv4 address")
        except ValueError as exc:
            raise ValueError(f"Invalid IPv4 address: {v}") from exc
        return v


class Alert(BaseModel):
    message: str
    severity: str  # "info" | "warning" | "critical"
    tick: int

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"info", "warning", "critical"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return v


class DPIEntry(BaseModel):
    src_ip: str
    dst_ip: str
    protocol: str
    payload_summary: str
    flags: list[str]


class DPITemplate(BaseModel):
    stage: KillChainStage
    entries: list[DPIEntry]
    ip_pool: list[str]


class DPISnapshot(BaseModel):
    stage: KillChainStage
    entries: list[DPIEntry]
    attacker_ip: str = ""
    decoy_ips: list[str] = []

    @field_serializer("attacker_ip")
    def _mask_attacker(self, v: str) -> str:
        return ""  # never expose attacker IP to agent

    @field_serializer("decoy_ips")
    def _mask_decoys(self, v: list) -> list:
        return []  # never expose decoy IPs to agent


class BusinessOutage(BaseModel):
    target_ip: str
    created_at_tick: int
    penalty_per_tick: float


class TaskConfig(BaseModel):
    max_steps: int
    stage_time_budgets: dict[KillChainStage, int]
    sla_penalty_rate: float
    num_decoys: int


class ResetRequest(BaseModel):
    seed: Optional[int] = 42
    session_id: Optional[str] = None


class GradeResult(BaseModel):
    reward: float
    outage_created: bool
    outage_resolved: bool
    survival_score: float


class Observation(BaseModel):
    stage: KillChainStage
    dpi_data: DPISnapshot
    alerts: list[Alert]
    survival_score: float
    tick: int
    done: bool
    dom: str
