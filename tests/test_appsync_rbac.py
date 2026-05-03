import json
import tempfile
import unittest
from pathlib import Path

from serverless.service.plugins.appsync.rbac import POLICY_PATH, RbacPolicy


class RbacPolicyTest(unittest.TestCase):
    def test_loads_manifest_roles_and_service_principals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / ".lara" / "rbac.yml"
            roles = root / "rbac-catalog" / "roles.yml"
            principals = root / "rbac-catalog" / "service-principals.yml"
            manifest.parent.mkdir(parents=True)
            roles.parent.mkdir(parents=True)
            manifest.write_text(
                """
version: 1
schema: lara.rbac.v1
repo: user-api
authorization:
  service: user-api
  default_effect: deny
  permissions: []
  surfaces:
    graphql:
      - surface: portal-public
        type: UsersMutation
        field: update
        access:
          type: permission
          permission: user-api:user:manage
          scope: organization
""".strip()
            )
            roles.write_text(
                """
version: 1
schema: lara.rbac.roles.v1
roles:
  portal_provider:
    display_name: Portal Provider
    app_roles:
      portalv2.lara.health:
        - provider
    legacy_aliases:
      - TEAM_MEMBER
    permissions:
      - grant: user-api:user:self-update
""".strip()
            )
            principals.write_text(
                """
version: 1
schema: lara.rbac.service-principals.v1
service_principals:
  portal-bff:
    display_name: Portal BFF
    allowed_callers:
      - arn:aws:iam::123:role/bff
    permissions:
      - grant: user-api:user:read
""".strip()
            )

            policy = RbacPolicy(
                manifest=".lara/rbac.yml",
                roles="rbac-catalog/roles.yml",
                service_principals="rbac-catalog/service-principals.yml",
                surface="portal-public",
                cwd=root,
            )

            encoded = json.loads(policy.policy_json())
            self.assertEqual(policy.entry_for("UsersMutation", "update")["access"]["permission"], "user-api:user:manage")
            self.assertEqual(encoded["legacy_aliases"]["TEAM_MEMBER"], "portal_provider")
            self.assertEqual(encoded["legacy_aliases"]["provider"], "portal_provider")
            self.assertEqual(encoded["role_grants"]["portal_provider"], ["user-api:user:self-update"])
            self.assertEqual(encoded["service_principal_grants"]["arn:aws:iam::123:role/bff"], ["user-api:user:read"])

            written = policy.write_policy_file()
            self.assertEqual(written, POLICY_PATH)
            self.assertEqual(json.loads((root / POLICY_PATH).read_text()), encoded)
            self.assertEqual(policy.package_manifest_path(), ".lara/rbac.yml")


if __name__ == "__main__":
    unittest.main()
