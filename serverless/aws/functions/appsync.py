import importlib
from pathlib import Path

from serverless.aws.functions.generic import Function
from serverless.service.plugins.appsync import AppSync
from serverless.service.plugins.appsync.plugin import ResolverExtra
from serverless.service.plugins.appsync.rbac import POLICY_PATH, RbacPolicy, vendor_lara_authz
from serverless.service.types import Identifier


def import_variable(module_name: str, variable_name: str):
    module = importlib.import_module(module_name)
    if not hasattr(module, variable_name):
        return None

    return getattr(module, variable_name)


class AppSyncFunction(Function):
    yaml_tag = "!AppSyncFunction"

    def __init__(self, service, name, description, handler=None, timeout=None, layers=None, **kwargs):
        super().__init__(service, name, description, handler, timeout, layers, **kwargs)

        module_name, function_name = self.handler.rsplit(".", 1)
        graphql_app = import_variable(module_name, "app")

        if not graphql_app:
            return

        plugin = service.plugins.get(AppSync)
        rbac_policy = RbacPolicy(
            manifest=plugin.rbac_manifest,
            roles=plugin.rbac_roles,
            service_principals=plugin.rbac_service_principals,
            surface=plugin.rbac_surface,
        )

        datasource_config = {
            'functionName': str(self.key.pascal)
        }

        if "provisionedConcurrency" in kwargs or "concurrencyAutoscaling" in kwargs:
            if isinstance(kwargs.get("concurrencyAutoscaling"), dict):
                fn_alias = kwargs.get("concurrencyAutoscaling", {}).get("alias", "provisioned")
            else:
                fn_alias = "provisioned"

            service.custom["ds" + str(self.key.pascal)] = {
                0: {
                    'functionName': str(self.key.pascal)
                },
                'default': {
                    'functionName': str(self.key.pascal),
                    'functionAlias': fn_alias
                }
            }

            datasource_config = '${self:custom.ds' + str(self.key.pascal) + '.${self:custom.vars.provisioning.provisionedConcurrency}, self:custom.ds'+ str(self.key.pascal) +'.default}'


        plugin.dataSources[str(self.key.pascal)] = {
            "type": "AWS_LAMBDA",
            "config": datasource_config
        }

        authz_function_name = "AuthzGate"
        business_function_name = str(self.key.pascal) + "Invoke"
        if rbac_policy.enabled and authz_function_name not in plugin.dataSources:
            policy_path = rbac_policy.write_policy_file()
            manifest_package_path = rbac_policy.package_manifest_path()
            vendor_lara_authz()
            authz_fn = Function(
                service,
                "authz-gate",
                "Generated AppSync RBAC authorization gate",
                handler="lara_authz.appsync.handler",
                environment={"LARA_AUTHZ_POLICY_PATH": policy_path},
            )
            authz_fn.package = {
                "individually": True,
                "patterns": [
                    "!./**/**",
                    "lara_authz/**",
                    manifest_package_path,
                    POLICY_PATH,
                ],
            }
            service.functions.add(authz_fn)
            plugin.dataSources[authz_function_name] = {
                "type": "AWS_LAMBDA",
                "config": {"functionName": str(authz_fn.key.pascal)},
            }

        extras_map = {extra.resolver.lower(): extra for extra in plugin.resolver_extras}

        has_query = False
        has_mutation = False

        import __main__ as main

        batch_resolver = Path(main.__file__).parent.absolute().joinpath("batch.response.vtl")
        with open(batch_resolver, "w+") as f:
            f.write("$util.toJson($context.result)")

        mutation_resolver = Path(main.__file__).parent.absolute().joinpath("mutation.response.vtl")
        with open(mutation_resolver, "w+") as f:
            f.write("""
#if (!$util.isNull($ctx.error))
  $util.error(
    $util.defaultIfNull($ctx.error.message, "UnhandledError"),
    $util.defaultIfNull($ctx.error.type, "Lambda:Unhandled"),
    $util.defaultIfNull($ctx.error.data, {}),
    $util.defaultIfNull($ctx.error.errorInfo, {})
  )
#end

#if (!$util.isNull($ctx.result) && !$util.isNull($ctx.result.error))
  $util.error(
    $util.defaultIfNull($ctx.result.error.message, "UnknownError"),
    $util.defaultIfNull($ctx.result.error.type, "BadRequest"),
    $util.defaultIfNull($ctx.result.error.data, {}),
    $util.defaultIfNull($ctx.result.error.info, {})
  )
#end

$util.toJson($ctx.result)
""".strip())

        lambda_request = Path(main.__file__).parent.absolute().joinpath("lambda.request.vtl")
        with open(lambda_request, "w+") as f:
            f.write("$util.toJson($context)")

        authz_response = Path(main.__file__).parent.absolute().joinpath("authz.response.vtl")
        with open(authz_response, "w+") as f:
            f.write("""
#if (!$util.isNull($ctx.error))
  $util.error("Forbidden", "Forbidden")
#end

#if (!$ctx.result.authorized)
  $util.error("Forbidden", "Forbidden", $ctx.result.context)
#end

$util.toJson($ctx.result)
""".strip())

        pipeline_response = Path(main.__file__).parent.absolute().joinpath("pipeline.response.vtl")
        with open(pipeline_response, "w+") as f:
            f.write("""
#if (!$util.isNull($ctx.error))
  $util.error(
    $util.defaultIfNull($ctx.error.message, "UnhandledError"),
    $util.defaultIfNull($ctx.error.type, "Lambda:Unhandled"),
    $util.defaultIfNull($ctx.error.data, {}),
    $util.defaultIfNull($ctx.error.errorInfo, {})
  )
#end

$util.toJson($ctx.prev.result)
""".strip())

        if rbac_policy.enabled:
            plugin.functions[authz_function_name] = {
                "dataSource": authz_function_name,
                "request": Path(lambda_request).name,
                "response": Path(authz_response).name,
            }
            plugin.functions[business_function_name] = {
                "dataSource": str(self.key.pascal),
                "request": Path(lambda_request).name,
                "response": Path(mutation_resolver).name,
            }

        for name, resolver in {
            **graphql_app._resolver_registry.resolvers,
            **graphql_app._batch_resolver_registry.resolvers,
        }.items():
            gql_type, gql_field = name.split(".")
            if gql_type.lower().endswith("query"):
                has_query = True

            if gql_type.lower().endswith("mutation"):
                has_mutation = True

            extras = extras_map.get(name.lower(), ResolverExtra(name))

            rbac_entry = rbac_policy.entry_for(gql_type, gql_field)
            defintion = {"type": gql_type, "field": gql_field, "kind": "UNIT", "dataSource": str(self.key.pascal)}
            if rbac_entry and gql_type.lower().endswith(("query", "mutation")):
                defintion = {
                    "type": gql_type,
                    "field": gql_field,
                    "kind": "PIPELINE",
                    "functions": [authz_function_name, business_function_name],
                    "response": Path(pipeline_response).name,
                }

            if name in graphql_app._batch_resolver_registry.resolvers:
                extras.max_batch_size = extras.max_batch_size or 10
                extras.response = extras.response or Path(batch_resolver).name

            if gql_type.lower().endswith("mutation"):
                extras.response = extras.response or Path(mutation_resolver).name

            if extras.max_batch_size and defintion.get("kind") == "UNIT":
                defintion["maxBatchSize"] = extras.max_batch_size

            if extras.response and defintion.get("kind") == "UNIT":
                defintion["response"] = extras.response

            if extras.request and defintion.get("kind") == "UNIT":
                defintion["request"] = extras.request

            plugin.resolvers[str(Identifier(gql_type).camel) + str(Identifier(gql_field).camel)] = defintion

        if plugin.namespace:
            parts = plugin.namespace.split(".")

            if has_query:
                if len(parts) == 1 or plugin.topNamespaceResolver:
                    plugin.resolvers["Query"] = {
                        "type": "Query",
                        "field": Identifier(parts[0]).camel.lower(),
                        "functions": [],
                    }
                if len(parts) > 1:
                    plugin.resolvers[Identifier(parts[0] + "Query").camel] = {
                        "type": Identifier(parts[0] + "Query").camel,
                        "field": Identifier(parts[1]).camel.lower(),
                        "functions": [],
                    }

            if has_mutation:
                if len(parts) == 1 or plugin.topNamespaceResolver:
                    plugin.resolvers["Mutation"] = {
                        "type": "Mutation",
                        "field": Identifier(parts[0]).camel.lower(),
                        "functions": [],
                    }

                if len(parts) > 1:
                    plugin.resolvers[Identifier(parts[0] + "Mutation").camel] = {
                        "type": Identifier(parts[0] + "Mutation").camel,
                        "field": Identifier(parts[1]).camel.lower(),
                        "functions": [],
                    }

    @classmethod
    def to_yaml(cls, dumper, data):
        return super().to_yaml(dumper, data)
