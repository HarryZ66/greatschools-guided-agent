"""GitHub Actions' access to this account (decision 039).

GitHub Actions signs in with OIDC: each workflow run gets a short-lived token from GitHub, and AWS
swaps it for temporary credentials. No AWS keys are stored in GitHub. Two roles:

- GsGitHubDeployRole: only for runs on `main` of this repo. It can do one thing, assume the CDK
  bootstrap roles, which is what `cdk deploy` needs; CloudFormation does the rest with the
  bootstrap's own permissions. Deploys GsDataStack and GsAppStack (.github/workflows/deploy.yml).
- GsGitHubEvalsRole: for pull requests from this repo and runs on `main`. Read-only: call Bedrock
  models, search OpenSearch, read the knowledge base and the stacks' outputs. Runs the evals
  (.github/workflows/evals.yml).

Deploy this stack once by hand (`cdk deploy GsCiStack`); the pipeline doesn't change its own access.
"""

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

GITHUB_REPO = "HarryZ66/greatschools-guided-agent"
GITHUB_OIDC = "token.actions.githubusercontent.com"


class CiStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        provider = iam.OidcProviderNative(self, "GitHubOidc", url=f"https://{GITHUB_OIDC}",
                                          client_ids=["sts.amazonaws.com"])

        def github(subjects: list[str]) -> iam.WebIdentityPrincipal:
            return iam.WebIdentityPrincipal(provider.oidc_provider_arn, conditions={
                "StringEquals": {f"{GITHUB_OIDC}:aud": "sts.amazonaws.com"},
                "StringLike": {f"{GITHUB_OIDC}:sub": subjects},
            })

        deploy = iam.Role(self, "DeployRole", role_name="GsGitHubDeployRole",
                          assumed_by=github([f"repo:{GITHUB_REPO}:ref:refs/heads/main"]),
                          description="GitHub Actions on main: cdk deploy through the CDK bootstrap roles")
        deploy.add_to_policy(iam.PolicyStatement(
            actions=["sts:AssumeRole", "sts:TagSession"],
            resources=[f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-*"]))

        evals = iam.Role(self, "EvalsRole", role_name="GsGitHubEvalsRole",
                         assumed_by=github([f"repo:{GITHUB_REPO}:pull_request",
                                            f"repo:{GITHUB_REPO}:ref:refs/heads/main"]),
                         description="GitHub Actions evals: read-only Bedrock, OpenSearch and knowledge base")
        evals.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=["arn:aws:bedrock:*::foundation-model/*",
                       f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/*"]))
        evals.add_to_policy(iam.PolicyStatement(
            actions=["es:ESHttpGet", "es:ESHttpPost"],  # searches are POSTs; no writes
            resources=[f"arn:aws:es:{self.region}:{self.account}:domain/*"]))
        evals.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:Retrieve"],
            resources=[f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/*"]))
        evals.add_to_policy(iam.PolicyStatement(
            actions=["cloudformation:DescribeStacks"],
            resources=[f"arn:aws:cloudformation:{self.region}:{self.account}:stack/Gs*/*"]))

        CfnOutput(self, "DeployRoleArn", value=deploy.role_arn)
        CfnOutput(self, "EvalsRoleArn", value=evals.role_arn)
