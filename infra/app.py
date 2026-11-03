#!/usr/bin/env python3
import os

import aws_cdk as cdk

from stacks.app_stack import AppStack
from stacks.data_stack import DataStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region="us-east-1",
)

data = DataStack(app, "GsDataStack", env=env)
AppStack(app, "GsAppStack", domain=data.domain, table=data.table, env=env)

cdk.Tags.of(app).add("project", "greatschools-guided-agent")

app.synth()
