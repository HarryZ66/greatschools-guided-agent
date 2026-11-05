#!/usr/bin/env python3
import os

import aws_cdk as cdk

from stacks.app_stack import AppStack
from stacks.ci_stack import CiStack
from stacks.data_stack import DataStack
from stacks.knowledge_stack import KnowledgeStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region="us-east-1",
)

data = DataStack(app, "GsDataStack", env=env)
# The parent guide's Bedrock Knowledge Base (decision 028). Standalone: no cross-stack exports.
KnowledgeStack(app, "GsKnowledgeStack", env=env)
# With -c knowledge_base_id=<id> (the GsKnowledgeStack output), the guide lookup uses the knowledge base
AppStack(app, "GsAppStack", domain=data.domain, table=data.table,
         knowledge_base_id=app.node.try_get_context("knowledge_base_id"), env=env)
# GitHub Actions' OIDC access (decision 039). Deployed once by hand; the pipeline doesn't deploy it.
CiStack(app, "GsCiStack", env=env)

cdk.Tags.of(app).add("project", "greatschools-guided-agent")

app.synth()
