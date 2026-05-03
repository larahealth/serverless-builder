# Repo Agent Report — LH-1858 — serverless-builder

## Status
done

## Execution context
- Catalog entry: present
- Repo AGENTS.md: present
- Base ref: `origin/master`
- Worktree: `worktrees/serverless-builder/LH-1858/`
- Toolchain: python + poetry
- Repo readiness issues: `poetry install` uses the host Python 3.14 build environment for a dependency build despite `poetry env use`, causing a pydantic-core/PyO3 build failure.

## Summary
- Added AppSync RBAC plugin options for service manifest, role catalog, service-principal catalog, and surface name.
- Added RBAC policy loading from `.lara/rbac.yml`, `rbac-catalog/roles.yml`, and `rbac-catalog/service-principals.yml`.
- Changed protected Query/Mutation resolvers to generated AppSync pipeline resolvers with `AuthzGate` before the business Lambda.
- Generated `.lara/generated/authz-policy.json` and configured `AuthzGate` to load policy from file instead of an oversized environment variable.
- Configured `AuthzGate` as an individually packaged function containing only `lara_authz/**`, `.lara/rbac.yml`, and `.lara/generated/authz-policy.json`.
- Added standard-library unit coverage for RBAC manifest, role alias, app role, and service-principal policy loading.

## Files changed
- `.lara/repo-manifest.yml`
- `serverless/aws/functions/appsync.py`
- `serverless/service/plugins/appsync/plugin.py`
- `serverless/service/plugins/appsync/rbac.py`
- `tests/test_appsync_rbac.py`

## Commands run + results
- CWD: `worktrees/serverless-builder/LH-1858`
  - `python -m compileall serverless/service/plugins/appsync serverless/aws/functions/appsync.py` → PASS
  - `python -m unittest discover -s tests` → PASS
  - `poetry build` → PASS
  - `poetry install` → FAIL

## Validation summary
- Repo standard checks: PARTIAL
- Additional validation: unittest and package build passed.
- Ad hoc env overrides used: None

## Interface / contract changes
- `AppSync(...)` accepts `rbac_manifest`, `rbac_roles`, `rbac_service_principals`, and `rbac_surface`.
- Generated Serverless AppSync config may now include an `AuthzGate` Lambda data source, AppSync functions, and pipeline resolvers.
- Generated `AuthzGate` functions set `package.individually: true` with minimal package patterns, include `.lara/rbac.yml`, and use `LARA_AUTHZ_POLICY_PATH`.

## Risks / rollout notes
- The generated `AuthzGate` handler requires the downstream service package to include `lara-authz`.
- Merge and release this package before regenerating and deploying RBAC-enabled services.

## PR / branch info
- Branch: `feature/LH-1858-appsync-rbac`
- PR: not created
- PR target/base branch: `master`
- Merge / publish order: release before `user-api` consumes the new AppSync options.
- Notes: None

## Blockers (if any)
- Command: `poetry install`
- Error: PyO3 rejects Python 3.14 while building `pydantic-core`.
- Needed: Poetry install executed with a supported Python <=3.13 build environment.
- Next step: Run setup in CI or a local Python 3.11/3.12 Poetry environment.
