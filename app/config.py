"""Application configuration loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core ---
    app_name: str = "NetPulse"
    secret_key: str = "dev-insecure-secret-change-me"
    access_token_expire_minutes: int = 720
    jwt_algorithm: str = "HS256"

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./netpulse.db"

    # --- Monitoring engine ---
    monitor_tick_seconds: int = 5
    max_concurrency: int = 200
    ping_privileged: bool = True
    down_failure_threshold: int = 1
    up_success_threshold: int = 1
    history_retention_days: int = 30
    metrics_retention_days: int = 14
    alert_renotify_minutes: int = 30
    latency_alert_cooldown_minutes: int = 10

    # --- SNMP defaults ---
    snmp_timeout: float = 3.0
    snmp_retries: int = 1
    snmp_default_port: int = 161
    snmp_max_interfaces: int = 64
    # Poll CPU/RAM/interfaces every N seconds (per device it uses device.interval if lower)
    metrics_interval_seconds: int = 60

    # --- Metric thresholds (defaults; per-device overrides in DB) ---
    cpu_threshold_percent: float = 85.0
    ram_threshold_percent: float = 90.0
    traffic_threshold_mbps: float = 0.0  # 0 = disabled

    # --- Vendor profiles ---
    vendor_profiles_dir: str = str(BASE_DIR / "app" / "vendors" / "profiles")

    # --- WireGuard ---
    wg_enabled: bool = False
    wg_interface: str = "wg0"
    wg_config_dir: str = "/etc/wireguard"
    wg_manage: bool = False  # allow API to write configs (needs root)

    # --- Telegram ---
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- First admin ---
    # NOTE: leave FIRST_ADMIN_PASSWORD empty in production. When empty, a random
    # password is generated on first run and printed once to the service log.
    # (scripts/setup.sh already writes a random value into .env.)
    first_admin_username: str = "admin"
    first_admin_password: str = ""
    first_admin_email: str = "admin@example.com"

    # --- Deployment ---
    cookie_secure: bool = False
    # Comma-separated CIDRs allowed to access the dashboard (empty = allow all)
    dashboard_allow_cidrs: str = ""

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def allow_cidrs(self) -> list[str]:
        return [c.strip() for c in self.dashboard_allow_cidrs.split(",") if c.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
