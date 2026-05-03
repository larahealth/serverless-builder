from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

POLICY_PATH = ".lara/generated/authz-policy.json"
DEFAULT_MANIFEST_PATH = ".lara/rbac.yml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def _find_upwards(start: Path, relative: str) -> Path | None:
    for path in [start, *start.parents]:
        candidate = path / relative
        if candidate.exists():
            return candidate
    return None


def _grant_value(grant: Any) -> str | None:
    if isinstance(grant, str):
        return grant
    if isinstance(grant, dict):
        value = grant.get("grant")
        return str(value) if value else None
    return None


def _role_policy(path: Path | None) -> tuple[dict[str, list[str]], dict[str, str]]:
    if path is None or not path.exists():
        return {}, {}
    roles = (_load_yaml(path).get("roles") or {})
    role_grants: dict[str, list[str]] = {}
    aliases: dict[str, str] = {}
    for role_name, role in roles.items():
        if not isinstance(role, dict):
            continue
        role_grants[str(role_name)] = [
            value for value in (_grant_value(item) for item in role.get("permissions") or []) if value
        ]
        for alias in role.get("legacy_aliases") or []:
            aliases[str(alias)] = str(role_name)
        for app_role_values in (role.get("app_roles") or {}).values():
            for app_role in app_role_values or []:
                aliases[str(app_role)] = str(role_name)
    return role_grants, aliases


def _service_principal_policy(path: Path | None) -> tuple[dict[str, list[str]], list[str]]:
    if path is None or not path.exists():
        return {}, []
    principals = (_load_yaml(path).get("service_principals") or {})
    grants: dict[str, list[str]] = {}
    trusted: list[str] = []
    for _name, principal in principals.items():
        if not isinstance(principal, dict):
            continue
        permissions = [
            value for value in (_grant_value(item) for item in principal.get("permissions") or []) if value
        ]
        for caller in principal.get("allowed_callers") or []:
            grants[str(caller)] = permissions
            trusted.append(str(caller))
    return grants, trusted


class RbacPolicy:
    def __init__(
        self,
        *,
        manifest: str | None,
        roles: str | None,
        service_principals: str | None,
        surface: str | None,
        cwd: Path | None = None,
    ):
        self.cwd = cwd or Path.cwd()
        self.manifest_path = Path(manifest) if manifest else None
        if self.manifest_path and not self.manifest_path.is_absolute():
            self.manifest_path = self.cwd / self.manifest_path
        self.roles_path = Path(roles) if roles else _find_upwards(self.cwd, "rbac-catalog/roles.yml")
        if self.roles_path and not self.roles_path.is_absolute():
            self.roles_path = self.cwd / self.roles_path
        self.service_principals_path = (
            Path(service_principals)
            if service_principals
            else _find_upwards(self.cwd, "rbac-catalog/service-principals.yml")
        )
        if self.service_principals_path and not self.service_principals_path.is_absolute():
            self.service_principals_path = self.cwd / self.service_principals_path
        self.surface = surface
        self.role_grants, self.legacy_aliases = _role_policy(self.roles_path)
        self.service_principal_grants, self.trusted_service_principals = _service_principal_policy(
            self.service_principals_path
        )
        self.graphql: dict[tuple[str | None, str, str], dict[str, Any]] = {}
        if self.manifest_path and self.manifest_path.exists():
            auth = _load_yaml(self.manifest_path).get("authorization") or {}
            for entry in ((auth.get("surfaces") or {}).get("graphql") or []):
                if not isinstance(entry, dict):
                    continue
                self.graphql[(entry.get("surface"), entry.get("type"), entry.get("field"))] = entry

    @property
    def enabled(self) -> bool:
        return bool(self.graphql)

    def entry_for(self, gql_type: str, gql_field: str) -> dict[str, Any] | None:
        return self.graphql.get((self.surface, gql_type, gql_field)) or self.graphql.get((None, gql_type, gql_field))

    def policy_json(self) -> str:
        entries = []
        for (_surface, gql_type, gql_field), entry in self.graphql.items():
            entries.append(
                {
                    "surface": entry.get("surface"),
                    "type": gql_type,
                    "field": gql_field,
                    "access": entry.get("access") or {},
                }
            )
        return json.dumps(
            {
                "surfaces": entries,
                "role_grants": self.role_grants,
                "legacy_aliases": self.legacy_aliases,
                "service_principal_grants": self.service_principal_grants,
                "trusted_service_principals": self.trusted_service_principals,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def write_policy_file(self, path: str = POLICY_PATH) -> str:
        policy_path = self.cwd / path
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(self.policy_json() + "\n", encoding="utf-8")
        return path

    def package_manifest_path(self) -> str:
        if not self.manifest_path:
            return DEFAULT_MANIFEST_PATH
        try:
            return str(self.manifest_path.relative_to(self.cwd))
        except ValueError:
            return DEFAULT_MANIFEST_PATH


def vendor_lara_authz(cwd: Path | None = None) -> None:
    import lara_authz

    root = cwd or Path.cwd()
    source = Path(lara_authz.__file__).parent
    target = root / "lara_authz"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "dist-info", "*.dist-info"),
    )
