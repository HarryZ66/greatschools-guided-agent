from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_opensearchservice as opensearch,
    aws_s3 as s3,
)
from constructs import Construct


class DataStack(Stack):
    """Search index, session store and data bucket.

    Deployed first because the OpenSearch domain takes 15-30 minutes to come up.
    Everything is set to be destroyed with the stack: this is a hackathon sandbox.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Single node, public HTTPS endpoint, IAM-signed requests only.
        # Any IAM principal in this account with es:ESHttp* permissions can reach it
        # (the agent's task role, and builders using their sandbox credentials).
        self.domain = opensearch.Domain(
            self,
            "SearchDomain",
            version=opensearch.EngineVersion.OPENSEARCH_2_19,
            capacity=opensearch.CapacityConfig(
                data_nodes=1,
                data_node_instance_type="t3.medium.search",
                multi_az_with_standby_enabled=False,
            ),
            ebs=opensearch.EbsOptions(volume_size=10),
            zone_awareness=opensearch.ZoneAwarenessConfig(enabled=False),
            enforce_https=True,
            node_to_node_encryption=True,
            encryption_at_rest=opensearch.EncryptionAtRestOptions(enabled=True),
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.domain.add_access_policies(
            iam.PolicyStatement(
                principals=[iam.AccountRootPrincipal()],
                actions=["es:ESHttp*"],
                resources=[f"{self.domain.domain_arn}/*"],
            )
        )

        # One table for sessions, saved schools and feedback.
        # pk = SESSION#<id>; sk = STATE | SAVED#<school_id> | FEEDBACK#<ts>
        self.table = dynamodb.Table(
            self,
            "AppTable",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.data_bucket = s3.Bucket(
            self,
            "DataBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        CfnOutput(self, "SearchEndpoint", value=f"https://{self.domain.domain_endpoint}")
        CfnOutput(self, "SearchDomainArn", value=self.domain.domain_arn)
        CfnOutput(self, "TableName", value=self.table.table_name)
        CfnOutput(self, "DataBucketName", value=self.data_bucket.bucket_name)
