"""Pydantic v2 request/response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import CheckType, DeviceStatus, EventSeverity, EventType, SnmpVersion


# ---------------------------------------------------------------- auth
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class UserBase(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)
    is_superuser: bool = False


class UserUpdate(BaseModel):
    """Admin update of another user (all fields optional)."""
    email: EmailStr | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class AdminPasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(UserBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool
    is_superuser: bool
    must_change_password: bool = False
    created_at: datetime


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


# ---------------------------------------------------------------- checks
class CheckBase(BaseModel):
    name: str = "check"
    type: CheckType
    params: dict = Field(default_factory=dict)
    enabled: bool = True
    latency_threshold_ms: float | None = None
    critical: bool = True


class CheckCreate(CheckBase):
    pass


class CheckOut(CheckBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    last_latency_ms: float | None = None
    last_success: bool | None = None
    last_error: str | None = None


# ---------------------------------------------------------------- devices
class SnmpConfigIn(BaseModel):
    """SNMP settings accepted on create/update. Secrets are encrypted at rest."""

    snmp_enabled: bool = False
    snmp_version: SnmpVersion = SnmpVersion.v2c
    snmp_port: int = Field(default=161, ge=1, le=65535)
    snmp_community: str | None = None  # write-only
    snmp_v3_user: str | None = None
    snmp_v3_auth_proto: str | None = None
    snmp_v3_auth_pass: str | None = None  # write-only
    snmp_v3_priv_proto: str | None = None
    snmp_v3_priv_pass: str | None = None  # write-only


class DeviceBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    vendor: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    interval_seconds: int = Field(default=60, ge=5, le=86400)
    timeout_seconds: float = Field(default=3.0, gt=0, le=60)
    latency_threshold_ms: float | None = Field(default=None, ge=0)
    notify: bool = True
    cpu_threshold: float | None = Field(default=None, ge=0, le=100)
    ram_threshold: float | None = Field(default=None, ge=0, le=100)
    metrics_interval_seconds: int | None = Field(default=None, ge=10, le=86400)


class DeviceCreate(DeviceBase, SnmpConfigIn):
    checks: list[CheckCreate] = Field(default_factory=list)


class DeviceUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    vendor: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    timeout_seconds: float | None = Field(default=None, gt=0, le=60)
    latency_threshold_ms: float | None = Field(default=None, ge=0)
    notify: bool | None = None
    cpu_threshold: float | None = Field(default=None, ge=0, le=100)
    ram_threshold: float | None = Field(default=None, ge=0, le=100)
    metrics_interval_seconds: int | None = Field(default=None, ge=10, le=86400)
    snmp_enabled: bool | None = None
    snmp_version: SnmpVersion | None = None
    snmp_port: int | None = Field(default=None, ge=1, le=65535)
    snmp_community: str | None = None
    snmp_v3_user: str | None = None
    snmp_v3_auth_proto: str | None = None
    snmp_v3_auth_pass: str | None = None
    snmp_v3_priv_proto: str | None = None
    snmp_v3_priv_pass: str | None = None


class DeviceOut(DeviceBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: DeviceStatus
    snmp_enabled: bool
    snmp_version: SnmpVersion
    snmp_port: int
    snmp_v3_user: str | None = None
    has_snmp_community: bool = False
    last_latency_ms: float | None = None
    last_cpu: float | None = None
    last_ram: float | None = None
    last_checked_at: datetime | None = None
    last_metrics_at: datetime | None = None
    last_change_at: datetime | None = None
    last_down_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    checks: list[CheckOut] = Field(default_factory=list)


class DeviceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    host: str
    vendor: str | None = None
    status: DeviceStatus
    last_latency_ms: float | None = None
    last_cpu: float | None = None
    last_ram: float | None = None
    last_checked_at: datetime | None = None
    uptime_percent: float | None = None


# ---------------------------------------------------------------- interfaces & metrics
class InterfaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    if_index: int
    if_name: str | None = None
    if_alias: str | None = None
    speed_bps: float | None = None
    monitor: bool
    oper_status: int | None = None
    last_in_bps: float | None = None
    last_out_bps: float | None = None
    last_polled_at: datetime | None = None


class MetricPoint(BaseModel):
    t: datetime
    v: float


class MetricSeries(BaseModel):
    metric: str
    unit: str | None = None
    points: list[MetricPoint] = Field(default_factory=list)


# ---------------------------------------------------------------- events
class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    type: EventType
    severity: EventSeverity
    message: str
    created_at: datetime
    resolved_at: datetime | None = None


class CheckResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    check_id: int
    timestamp: datetime
    success: bool
    latency_ms: float | None = None
    error: str | None = None


# ---------------------------------------------------------------- misc
class StatsOut(BaseModel):
    total: int
    up: int
    down: int
    unknown: int
    avg_latency_ms: float | None = None
    avg_cpu: float | None = None
    avg_ram: float | None = None
    events_last_24h: int = 0


class VendorProfileOut(BaseModel):
    key: str
    label: str
    cpu: str | None = None
    ram: str | None = None
    description: str | None = None


class WireGuardPeer(BaseModel):
    public_key: str | None = None
    endpoint: str | None = None
    allowed_ips: str | None = None
    latest_handshake: str | None = None
    transfer_rx: str | None = None
    transfer_tx: str | None = None


class WireGuardStatus(BaseModel):
    enabled: bool
    interface: str
    installed: bool
    up: bool
    listen_port: int | None = None
    peers: list[WireGuardPeer] = Field(default_factory=list)
    message: str | None = None


class MessageOut(BaseModel):
    detail: str


class TelegramSettingsIn(BaseModel):
    enabled: bool | None = None
    bot_token: str | None = None      # write-only; stored encrypted
    chat_id: str | None = None


class TelegramSettingsOut(BaseModel):
    enabled: bool
    chat_id: str | None = None
    has_token: bool
    ready: bool


class WhatsAppSettingsIn(BaseModel):
    enabled: bool | None = None
    phone: str | None = None       # e.g. +8801XXXXXXXXX
    apikey: str | None = None      # write-only; stored encrypted


class WhatsAppSettingsOut(BaseModel):
    enabled: bool
    phone: str | None = None
    has_apikey: bool
    ready: bool
