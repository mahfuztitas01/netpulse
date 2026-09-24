"""Role-based access control (RBAC).

Roles (least privilege):
    super_admin - full access including user management
    admin       - manage devices/groups/alerts/settings, cannot manage users
    operator    - view everything, acknowledge alerts, trigger on-demand checks
    viewer      - read-only

Permissions are coarse-grained per resource: ``None`` = no access, ``"read"`` =
view only, ``"write"`` = full CRUD. The table below is the single source of
truth; ``can()`` is the shared lookup used by the FastAPI dependency and by
future API endpoints.
"""
from __future__ import annotations

from .models import UserRole

# resource -> minimum role for write access (everything is readable by viewer+)
WRITE_ACCESS: dict[str, set[str]] = {
    "users": {"super_admin"},
    "devices": {"super_admin", "admin"},
    "groups": {"super_admin", "admin"},
    "alerts": {"super_admin", "admin", "operator"},  # ack/resolve only
    "settings": {"super_admin", "admin"},
    "reports": {"super_admin", "admin", "operator"},
}

# resources a viewer may still see
READ_ACCESS: dict[str, set[str]] = {
    "users": {"super_admin", "admin"},
    "devices": {"super_admin", "admin", "operator", "viewer"},
    "groups": {"super_admin", "admin", "operator", "viewer"},
    "alerts": {"super_admin", "admin", "operator", "viewer"},
    "settings": {"super_admin", "admin"},
    "reports": {"super_admin", "admin", "operator", "viewer"},
}


def can(role: str | UserRole | None, resource: str, action: str = "read") -> bool:
    """Return True if ``role`` may perform ``action`` (read/write) on ``resource``."""
    if role is None:
        return False
    name = role.value if isinstance(role, UserRole) else str(role)
    table = WRITE_ACCESS if action == "write" else READ_ACCESS
    return name in table.get(resource, set())


def role_order(role: str | UserRole | None) -> int:
    """Numeric rank so we can gate ``operator+`` style checks."""
    order = {"super_admin": 3, "admin": 2, "operator": 1, "viewer": 0}
    name = role.value if isinstance(role, UserRole) else str(role)
    return order.get(name or "", -1)
