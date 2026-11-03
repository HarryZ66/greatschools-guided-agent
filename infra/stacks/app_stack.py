from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_opensearchservice as opensearch,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]


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

        # One task: conversations are kept in memory (see agent/gs_agent/api.py).
        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "AgentService",
            cluster=cluster,
            cpu=1024,
            memory_limit_mib=2048,
            desired_count=1,
            public_load_balancer=True,
            open_listener=False,  # only CloudFront may reach it; see the ingress rule below
            assign_public_ip=True,
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            runtime_platform=ecs.RuntimePlatform(cpu_architecture=ecs.CpuArchitecture.ARM64,
                                                 operating_system_family=ecs.OperatingSystemFamily.LINUX),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(str(REPO_ROOT / "agent")),
                container_port=8000,
                environment={
                    "AWS_REGION": self.region,
                    "AWS_DEFAULT_REGION": self.region,
                    "SEARCH_ENDPOINT": f"https://{domain.domain_endpoint}",
                    "TABLE_NAME": table.table_name,
                },
            ),
            idle_timeout=Duration.seconds(120),
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )
        service.target_group.configure_health_check(path="/api/health", healthy_http_codes="200")

        # The ALB has a public address (no NAT, see docs/decisions.md 005), but it only accepts
        # traffic from CloudFront's origin-facing IP ranges, so nobody can skip the HTTPS URL.
        cloudfront_ips = ec2.PrefixList.from_lookup(
            self, "CloudFrontOriginFacing", prefix_list_name="com.amazonaws.global.cloudfront.origin-facing")
        service.load_balancer.connections.allow_from(
            ec2.Peer.prefix_list(cloudfront_ips.prefix_list_id), ec2.Port.tcp(80), "CloudFront only")
        service.target_group.set_attribute("deregistration_delay.timeout_seconds", "10")

        task_role = service.task_definition.task_role
        domain.grant_read_write(task_role)
        table.grant_read_write_data(task_role)
        task_role.add_to_principal_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                "arn:aws:bedrock:*::foundation-model/*",  # cross-region profiles route to several regions
                f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/*",
            ],
        ))

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
        distribution = cloudfront.Distribution(
            self, "Distribution",
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
