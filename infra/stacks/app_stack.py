import json
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_bedrockagentcore as agentcore,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_opensearchservice as opensearch,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_secretsmanager as secretsmanager,
    aws_wafv2 as wafv2,
    aws_xray as xray,
)
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]

# AWS-managed prefix list of CloudFront's origin-facing addresses in us-east-1
# (aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing)
CLOUDFRONT_PREFIX_LIST = "pl-3b927c52"
# Agent turns allowed per IP address per 5 minutes; a parent uses a few per minute
TURN_RATE_LIMIT = 300
# The Gateway's MCP tools, shared with the Lambda handler (agent/gs_agent/gateway_tools.py)
GATEWAY_TOOLS = json.loads((REPO_ROOT / "agent" / "gs_agent" / "gateway_tools.json").read_text())


def _schema(s: dict) -> agentcore.CfnGatewayTarget.SchemaDefinitionProperty:
    """A JSON schema from gateway_tools.json as the Gateway target's schema type."""
    return agentcore.CfnGatewayTarget.SchemaDefinitionProperty(
        type=s["type"], description=s.get("description"), required=s.get("required"),
        items=_schema(s["items"]) if "items" in s else None,
        properties={k: _schema(v) for k, v in s["properties"].items()} if "properties" in s else None)


class AppStack(Stack):
    """Agent API on Fargate behind an ALB, and the frontend on S3, both served by one CloudFront URL.

    CloudFront routes /api/* to the ALB and everything else to the frontend bucket, so the
    browser talks to a single HTTPS origin and needs no CORS.
    """

    def __init__(self, scope: Construct, construct_id: str, *, domain: opensearch.Domain,
                 table: dynamodb.Table, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Public subnets only, no NAT gateway: cheaper and faster to create. The task gets a
        # public IP to reach Bedrock, OpenSearch and DynamoDB. Production would use private subnets.
        vpc = ec2.Vpc(self, "Vpc", max_azs=2, nat_gateways=0,
                      subnet_configuration=[ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC)])
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, container_insights_v2=ecs.ContainerInsights.DISABLED)

        log_group = logs.LogGroup(self, "AgentLogs", retention=logs.RetentionDays.TWO_WEEKS,
                                  removal_policy=RemovalPolicy.DESTROY)

        # One image for both the public API (Fargate) and the agent (AgentCore Runtime). Built for
        # ARM64 whatever machine runs the deploy (both run on Graviton); an x86 laptop would
        # otherwise build an amd64 image that exits at once (exit code 255, no logs).
        image = ecr_assets.DockerImageAsset(self, "AgentImage", directory=str(REPO_ROOT / "agent"),
                                            platform=ecr_assets.Platform.LINUX_ARM64)

        # Agent turns run on Amazon Bedrock AgentCore Runtime (docs/decisions.md, 025): one session
        # per parent's conversation, paid per use. Public network mode: it reaches Bedrock,
        # OpenSearch (IAM-signed) and DynamoDB over HTTPS, like the Fargate task.
        runtime_role = iam.Role(self, "AgentRuntimeRole",
                                assumed_by=iam.ServicePrincipal(
                                    "bedrock-agentcore.amazonaws.com",
                                    conditions={"StringEquals": {"aws:SourceAccount": self.account}}))
        image.repository.grant_pull(runtime_role)
        runtime_role.add_to_principal_policy(iam.PolicyStatement(
            actions=["ecr:GetAuthorizationToken"], resources=["*"]))
        runtime_role.add_to_principal_policy(iam.PolicyStatement(
            actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",
                     "logs:DescribeLogGroups", "logs:DescribeLogStreams"],
            resources=[f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/runtimes/*"]))
        runtime_role.add_to_principal_policy(iam.PolicyStatement(
            actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules",
                     "xray:GetSamplingTargets", "cloudwatch:PutMetricData"],
            resources=["*"]))

        # Front door (decision 026): the runtime accepts only OAuth access tokens issued by this
        # Cognito user pool to the API's app client (inbound auth through AgentCore Identity).
        # Machine-to-machine: the API gets tokens with the client-credentials grant; no parent signs in.
        user_pool = cognito.UserPool(self, "AgentUserPool", self_sign_up_enabled=False,
                                     removal_policy=RemovalPolicy.DESTROY)
        invoke_scope = cognito.ResourceServerScope(scope_name="invoke", scope_description="Call the agent runtime")
        resource_server = user_pool.add_resource_server(
            "AgentResourceServer", identifier="greatschools-agent", scopes=[invoke_scope])
        token_domain = user_pool.add_domain("AgentTokenDomain", cognito_domain=cognito.CognitoDomainOptions(
            domain_prefix=f"greatschools-agent-{self.account}"))
        api_client = user_pool.add_client(
            "ApiClient", generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(client_credentials=True),
                scopes=[cognito.OAuthScope.resource_server(resource_server, invoke_scope)]),
            access_token_validity=Duration.minutes(60))
        # Handed to the API task as an ECS secret, never as a plain environment variable
        api_client_secret = secretsmanager.Secret(
            self, "ApiClientSecret", description="Cognito client secret the API uses to call the agent runtime",
            secret_string_value=api_client.user_pool_client_secret, removal_policy=RemovalPolicy.DESTROY)
        discovery_url = (f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}"
                         "/.well-known/openid-configuration")

        # AgentCore Gateway (decision 027): the agent's data lookups as MCP tools, served by one
        # Lambda function from the same code. IAM inbound auth: only the runtime's role may call it.
        tools_fn = lambda_.DockerImageFunction(
            self, "GatewayToolsFunction",
            code=lambda_.DockerImageCode.from_image_asset(
                str(REPO_ROOT / "agent"), file="Dockerfile.tools", platform=ecr_assets.Platform.LINUX_ARM64),
            architecture=lambda_.Architecture.ARM_64, memory_size=1024, timeout=Duration.seconds(30),
            description="GreatSchools agent data tools behind the AgentCore Gateway",
            environment={"SEARCH_ENDPOINT": f"https://{domain.domain_endpoint}"},
            log_group=logs.LogGroup(self, "GatewayToolsLogs", retention=logs.RetentionDays.TWO_WEEKS,
                                    removal_policy=RemovalPolicy.DESTROY))
        # Read-only, but searches are POSTs (grant_read only allows GET and HEAD)
        tools_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["es:ESHttpGet", "es:ESHttpHead", "es:ESHttpPost"], resources=[f"{domain.domain_arn}/*"]))
        tools_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],  # Titan embeddings for the guide and program searches
            resources=[f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0"]))

        gateway_role = iam.Role(self, "GatewayRole", assumed_by=iam.ServicePrincipal(
            "bedrock-agentcore.amazonaws.com", conditions={"StringEquals": {"aws:SourceAccount": self.account}}))
        tools_fn.grant_invoke(gateway_role)
        gateway = agentcore.CfnGateway(
            self, "ToolsGateway", name="greatschools-tools", protocol_type="MCP", authorizer_type="AWS_IAM",
            role_arn=gateway_role.role_arn, description="GreatSchools data tools for the guided search agent")
        gateway.node.add_dependency(gateway_role)
        tools_target = agentcore.CfnGatewayTarget(
            self, "ToolsGatewayTarget", gateway_identifier=gateway.attr_gateway_identifier, name="gs-data",
            description="Parent guide, programs, school by name, school record",
            target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                    lambda_=agentcore.CfnGatewayTarget.McpLambdaTargetConfigurationProperty(
                        lambda_arn=tools_fn.function_arn,
                        tool_schema=agentcore.CfnGatewayTarget.ToolSchemaProperty(inline_payload=[
                            agentcore.CfnGatewayTarget.ToolDefinitionProperty(
                                name=t["name"], description=t["description"], input_schema=_schema(t["inputSchema"]))
                            for t in GATEWAY_TOOLS])))),
            credential_provider_configurations=[agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                credential_provider_type="GATEWAY_IAM_ROLE")])
        tools_target.node.add_dependency(gateway_role)
        runtime_role.add_to_principal_policy(iam.PolicyStatement(
            actions=["bedrock-agentcore:InvokeGateway"], resources=[gateway.attr_gateway_arn]))

        runtime = agentcore.CfnRuntime(
            self, "AgentRuntime",
            agent_runtime_name="greatschools_guided_agent",
            description="GreatSchools guided search agent (Strands on Bedrock)",
            role_arn=runtime_role.role_arn,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=image.image_uri)),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(network_mode="PUBLIC"),
            protocol_configuration="HTTP",
            # Calls without a valid token from this pool and client are rejected (and SigV4 calls too)
            authorizer_configuration=agentcore.CfnRuntime.AuthorizerConfigurationProperty(
                custom_jwt_authorizer=agentcore.CfnRuntime.CustomJWTAuthorizerConfigurationProperty(
                    discovery_url=discovery_url, allowed_clients=[api_client.user_pool_client_id])),
            # A parent may pause to read results: keep the conversation for 30 idle minutes
            lifecycle_configuration=agentcore.CfnRuntime.LifecycleConfigurationProperty(
                idle_runtime_session_timeout=1800, max_lifetime=8 * 3600),
            environment_variables={
                "PORT": "8080",
                "RUNNING_ON": "agentcore",
                "GATEWAY_URL": gateway.attr_gateway_url,
                "GATEWAY_TARGET": "gs-data",
                "AWS_REGION": self.region,
                "AWS_DEFAULT_REGION": self.region,
                "SEARCH_ENDPOINT": f"https://{domain.domain_endpoint}",
                "TABLE_NAME": table.table_name,
            },
        )
        runtime.node.add_dependency(runtime_role)

        # AgentCore Observability (decision 026). CloudWatch Transaction Search stores X-Ray spans
        # in CloudWatch Logs, where the GenAI Observability dashboard reads them. The agent sends its
        # own spans (ADOT, see agent/Dockerfile); the runtime also delivers its logs and traces.
        # Transaction Search is an account setting: deleting this stack turns it back off.
        xray_policy = logs.CfnResourcePolicy(
            self, "TransactionSearchLogsPolicy", policy_name="greatschools-transaction-search",
            policy_document=json.dumps({"Version": "2012-10-17", "Statement": [{
                "Sid": "TransactionSearchXRayAccess", "Effect": "Allow",
                "Principal": {"Service": "xray.amazonaws.com"}, "Action": "logs:PutLogEvents",
                "Resource": [f"arn:aws:logs:{self.region}:{self.account}:log-group:aws/spans:*",
                             f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/application-signals/data:*"],
                "Condition": {"ArnLike": {"aws:SourceArn": f"arn:aws:xray:{self.region}:{self.account}:*"},
                              "StringEquals": {"aws:SourceAccount": self.account}}}]}))
        # Index every span: a demo sends few, and partial sampling would hide some turns
        transaction_search = xray.CfnTransactionSearchConfig(self, "TransactionSearch", indexing_percentage=100)
        transaction_search.add_dependency(xray_policy)

        runtime_app_logs = logs.LogGroup(self, "AgentRuntimeAppLogs", retention=logs.RetentionDays.TWO_WEEKS,
                                         removal_policy=RemovalPolicy.DESTROY)
        for log_type, destination in (
            ("APPLICATION_LOGS", logs.CfnDeliveryDestination(
                self, "RuntimeLogsDestination", name="greatschools-runtime-logs",
                delivery_destination_type="CWL", destination_resource_arn=runtime_app_logs.log_group_arn)),
            ("TRACES", logs.CfnDeliveryDestination(
                self, "RuntimeTracesDestination", name="greatschools-runtime-traces",
                delivery_destination_type="XRAY")),
        ):
            source = logs.CfnDeliverySource(
                self, f"Runtime{log_type.title().replace('_', '')}Source",
                name=f"greatschools-runtime-{log_type.lower().replace('_', '-')}",
                log_type=log_type, resource_arn=runtime.attr_agent_runtime_arn)
            delivery = logs.CfnDelivery(self, f"Runtime{log_type.title().replace('_', '')}Delivery",
                                        delivery_source_name=source.name,
                                        delivery_destination_arn=destination.attr_arn)
            delivery.add_dependency(source)
            delivery.add_dependency(transaction_search)

        # One task: conversations live on AgentCore Runtime (see agent/gs_agent/api.py).
        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "AgentService",
            cluster=cluster,
            cpu=1024,
            memory_limit_mib=2048,
            desired_count=1,
            public_load_balancer=True,
            # Only CloudFront may reach the load balancer (rule added below), so WAF can't be bypassed
            open_listener=False,
            assign_public_ip=True,
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            runtime_platform=ecs.RuntimePlatform(cpu_architecture=ecs.CpuArchitecture.ARM64,
                                                 operating_system_family=ecs.OperatingSystemFamily.LINUX),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_docker_image_asset(image),
                container_port=8000,
                log_driver=ecs.LogDrivers.aws_logs(stream_prefix="agent", log_group=log_group),
                environment={
                    "AWS_REGION": self.region,
                    "AWS_DEFAULT_REGION": self.region,
                    "SEARCH_ENDPOINT": f"https://{domain.domain_endpoint}",
                    "TABLE_NAME": table.table_name,
                    "AGENT_RUNTIME_ARN": runtime.attr_agent_runtime_arn,
                    "OAUTH_TOKEN_URL": f"{token_domain.base_url()}/oauth2/token",
                    "OAUTH_CLIENT_ID": api_client.user_pool_client_id,
                    "OAUTH_SCOPE": f"{resource_server.user_pool_resource_server_id}/{invoke_scope.scope_name}",
                },
                secrets={"OAUTH_CLIENT_SECRET": ecs.Secret.from_secrets_manager(api_client_secret)},
            ),
            idle_timeout=Duration.seconds(120),
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )
        service.load_balancer.connections.allow_from(ec2.Peer.prefix_list(CLOUDFRONT_PREFIX_LIST), ec2.Port.tcp(80),
                                                     "HTTP from CloudFront only")
        service.target_group.configure_health_check(path="/api/health", healthy_http_codes="200")
        service.target_group.set_attribute("deregistration_delay.timeout_seconds", "10")

        task_role = service.task_definition.task_role
        # The API reads schools and writes saves itself; the agent's model calls run on the runtime.
        # Both keep Bedrock access so the API still works alone (AGENT_RUNTIME_ARN unset).
        for role in (task_role, runtime_role):
            domain.grant_read_write(role)
            table.grant_read_write_data(role)
            role.add_to_principal_policy(iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/*",  # cross-region profiles route to several regions
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/*",
                ],
            ))
        # AgentCore checks the role can pull the image when the runtime is created
        runtime.node.add_dependency(runtime_role.node.find_child("DefaultPolicy"))

        # Frontend: built app if it exists, otherwise a placeholder page.
        site_bucket = s3.Bucket(self, "SiteBucket", block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                                enforce_ssl=True, removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True)
        dist = REPO_ROOT / "frontend" / "dist"
        site_source = dist if (dist / "index.html").exists() else REPO_ROOT / "frontend" / "placeholder"

        api_origin = origins.LoadBalancerV2Origin(
            service.load_balancer,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
            read_timeout=Duration.seconds(60),
        )
        # WAF: cap agent turns per IP (each one calls Bedrock) and block known-bad IPs.
        # CloudFront web ACLs must live in us-east-1, which is where this stack deploys.
        web_acl = wafv2.CfnWebACL(
            self, "WebAcl",
            scope="CLOUDFRONT",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True, metric_name="gs-web-acl", sampled_requests_enabled=True),
            rules=[
                wafv2.CfnWebACL.RuleProperty(
                    name="rate-limit-agent-turns", priority=0,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                        limit=TURN_RATE_LIMIT, aggregate_key_type="IP", evaluation_window_sec=300,
                        scope_down_statement=wafv2.CfnWebACL.StatementProperty(
                            byte_match_statement=wafv2.CfnWebACL.ByteMatchStatementProperty(
                                field_to_match=wafv2.CfnWebACL.FieldToMatchProperty(uri_path={}),
                                positional_constraint="STARTS_WITH", search_string="/api/turn",
                                text_transformations=[wafv2.CfnWebACL.TextTransformationProperty(priority=0, type="NONE")])))),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True, metric_name="rate-limit-agent-turns", sampled_requests_enabled=True)),
                wafv2.CfnWebACL.RuleProperty(
                    name="aws-ip-reputation", priority=1,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                        vendor_name="AWS", name="AWSManagedRulesAmazonIpReputationList")),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True, metric_name="aws-ip-reputation", sampled_requests_enabled=True)),
            ],
        )

        distribution = cloudfront.Distribution(
            self, "Distribution",
            web_acl_id=web_acl.attr_arn,
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
            },
            # Single-page app: unknown paths serve index.html
            error_responses=[cloudfront.ErrorResponse(http_status=403, response_http_status=200,
                                                      response_page_path="/index.html", ttl=Duration.seconds(0))],
        )
        s3deploy.BucketDeployment(self, "DeploySite", sources=[s3deploy.Source.asset(str(site_source))],
                                  destination_bucket=site_bucket, distribution=distribution,
                                  distribution_paths=["/*"])

        CfnOutput(self, "AppUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "ApiUrl", value=f"https://{distribution.distribution_domain_name}/api")
        CfnOutput(self, "AgentRuntimeArn", value=runtime.attr_agent_runtime_arn)
        CfnOutput(self, "GatewayUrl", value=gateway.attr_gateway_url)
        # For agent/scripts/check_front_door.py (no secrets: the client secret stays in Secrets Manager)
        CfnOutput(self, "OAuthTokenUrl", value=f"{token_domain.base_url()}/oauth2/token")
        CfnOutput(self, "OAuthClientId", value=api_client.user_pool_client_id)
        CfnOutput(self, "OAuthScope", value=f"{resource_server.user_pool_resource_server_id}/{invoke_scope.scope_name}")
        CfnOutput(self, "OAuthClientSecretArn", value=api_client_secret.secret_arn)
        CfnOutput(self, "LoadBalancerUrl", value=f"http://{service.load_balancer.load_balancer_dns_name}")
