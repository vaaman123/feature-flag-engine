"""
Pydantic models for the Feature Flag Engine.
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime, timezone, timedelta
import uuid

IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> str:
    return datetime.now(IST).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


# ─── Targeting ───────────────────────────────────────────────────────────────

class TargetingConfig(BaseModel):
    type: Literal["everyone", "beta_users", "percentage", "user_ids"] = "everyone"
    percentage: Optional[float] = None   # 0–100, used when type="percentage"
    user_ids: List[str] = []             # used when type="user_ids"


# ─── Feature Flags ───────────────────────────────────────────────────────────

class FeatureFlag(BaseModel):
    id: str = Field(default_factory=_uuid)
    name: str
    enabled: bool = False
    targeting: TargetingConfig = Field(default_factory=TargetingConfig)
    description: str = ""
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


class CreateFlagRequest(BaseModel):
    name: str
    enabled: bool = False
    targeting: TargetingConfig = Field(default_factory=TargetingConfig)
    description: str = ""


class UpdateFlagRequest(BaseModel):
    enabled: Optional[bool] = None
    targeting: Optional[TargetingConfig] = None
    description: Optional[str] = None


# ─── Remote Configs ──────────────────────────────────────────────────────────

class RemoteConfig(BaseModel):
    id: str = Field(default_factory=_uuid)
    key: str
    value: str           # Always stored as a string; type field controls parsing
    type: Literal["string", "number", "boolean"] = "string"
    description: str = ""
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


class CreateConfigRequest(BaseModel):
    key: str
    value: str
    type: Literal["string", "number", "boolean"] = "string"
    description: str = ""


class UpdateConfigRequest(BaseModel):
    value: Optional[str] = None
    type: Optional[Literal["string", "number", "boolean"]] = None
    description: Optional[str] = None


# ─── Evaluation ──────────────────────────────────────────────────────────────

class EvaluateRequest(BaseModel):
    user_id: str = "anonymous"
    is_beta_user: bool = False
    flag_names: Optional[List[str]] = None   # None → evaluate all flags


class EvaluateResponse(BaseModel):
    user_id: str
    flags: dict[str, bool]
    configs: dict[str, object]
