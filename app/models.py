"""SQLAlchemy ORM models."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- enums
class DeviceStatus(str, enum.Enum):
    unknown = "unknown"
    up = "up"
    down = "down"


class CheckType(str, enum.Enum):
    ping = "ping"
    tcp = "tcp"
    snmp = "snmp"
    http = "http"


class EventType(str, enum.Enum):
    down = "down"
    up = "up"
    high_latency = "high_latency"
    high_cpu = "high_cpu"
    high_ram = "high_ram"
    info = "info"


class EventSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class SnmpVersion(str, enum.Enum):
    v1 = "1"
    v2c = "2c"
    v3 = "3"


# ---------------------------------------------------------------- user
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    # When True the user must change their password before using the app
    # (set for the auto-created first admin so a generated password is one-time).
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---------------------------------------------------------------- device
class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    host: Mapped[str] = mapped_column(String(255), index=True)
    vendor: Mapped[str | None] = mapped_column(String(64), nullable=True)  # mikrotik/cisco/unifi/olt/generic
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=3.0)
    latency_threshold_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- SNMP (secrets stored encrypted, see app.crypto) ---
    snmp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    snmp_version: Mapped[SnmpVersion] = mapped_column(
        SAEnum(SnmpVersion, native_enum=False, length=8), default=SnmpVersion.v2c
    )
    snmp_port: Mapped[int] = mapped_column(Integer, default=161)
    snmp_community_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    snmp_v3_user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snmp_v3_auth_proto: Mapped[str | None] = mapped_column(String(16), nullable=True)  # SHA/MD5
    snmp_v3_auth_pass_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    snmp_v3_priv_proto: Mapped[str | None] = mapped_column(String(16), nullable=True)  # AES/DES
    snmp_v3_priv_pass_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # --- metric thresholds (per device overrides) ---
    cpu_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    ram_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- live state ---
    status: Mapped[DeviceStatus] = mapped_column(
        SAEnum(DeviceStatus, native_enum=False, length=16),
        default=DeviceStatus.unknown,
        index=True,
    )
    last_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_change_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_down_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_metrics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0)

    # latest metric snapshots (for fast dashboard reads)
    last_cpu: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_ram: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    checks: Mapped[list["Check"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", lazy="selectin"
    )
    interfaces: Mapped[list["Interface"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
    events: Mapped[list["Event"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )

    @property
    def has_snmp_community(self) -> bool:
        return bool(self.snmp_community_enc)


# ---------------------------------------------------------------- check
class Check(Base):
    __tablename__ = "checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), default="check")
    type: Mapped[CheckType] = mapped_column(SAEnum(CheckType, native_enum=False, length=16))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    latency_threshold_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical: Mapped[bool] = mapped_column(Boolean, default=True)

    last_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    device: Mapped["Device"] = relationship(back_populates="checks")
    results: Mapped[list["CheckResult"]] = relationship(
        back_populates="check", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------- history
class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("checks.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    success: Mapped[bool] = mapped_column(Boolean, index=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    check: Mapped["Check"] = relationship(back_populates="results")

    __table_args__ = (Index("ix_results_device_time", "device_id", "timestamp"),)


# ---------------------------------------------------------------- interfaces
class Interface(Base):
    __tablename__ = "interfaces"
    __table_args__ = (
        UniqueConstraint("device_id", "if_index", name="uq_interface_device_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    if_index: Mapped[int] = mapped_column(Integer)
    if_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    if_alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    if_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    monitor: Mapped[bool] = mapped_column(Boolean, default=True)

    # live values
    last_in_octets: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_out_octets: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_in_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_out_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    oper_status: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1=up 2=down

    device: Mapped["Device"] = relationship(back_populates="interfaces")


class InterfaceSample(Base):
    __tablename__ = "interface_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    interface_id: Mapped[int] = mapped_column(ForeignKey("interfaces.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    in_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_bps: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (Index("ix_iface_sample_time", "interface_id", "timestamp"),)


# ---------------------------------------------------------------- metrics
class MetricSample(Base):
    """Generic numeric time-series (cpu, ram, uptime, temperature...)."""

    __tablename__ = "metric_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(48), index=True)
    value: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (Index("ix_metric_device_name_time", "device_id", "metric", "timestamp"),)


# ---------------------------------------------------------------- events
class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    type: Mapped[EventType] = mapped_column(SAEnum(EventType, native_enum=False, length=16), index=True)
    severity: Mapped[EventSeverity] = mapped_column(
        SAEnum(EventSeverity, native_enum=False, length=16), default=EventSeverity.info
    )
    message: Mapped[str] = mapped_column(Text)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    device: Mapped["Device"] = relationship(back_populates="events")


# ---------------------------------------------------------------- settings KV
class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_app_settings_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
