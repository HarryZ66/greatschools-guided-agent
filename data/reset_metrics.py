"""Delete all searches, saves, feedback and visit requests from the app table, so /api/metrics starts at zero.

Run it right before a demo: test runs create searches without saves and skew saves-to-searches.

    AWS_PROFILE=gs-sandbox AWS_DEFAULT_REGION=us-east-1 .venv/bin/python data/reset_metrics.py --yes
"""

import argparse
import json
import sys
from pathlib import Path

import boto3

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="actually delete (otherwise only count)")
    args = parser.parse_args()

    name = json.loads((REPO_ROOT / "infra/cdk-outputs.json").read_text())["GsDataStack"]["TableName"]
    table = boto3.Session(region_name="us-east-1").resource("dynamodb").Table(name)

    keys, kwargs = [], {"ProjectionExpression": "pk, sk"}
    while True:
        page = table.scan(**kwargs)
        keys += [{"pk": i["pk"], "sk": i["sk"]} for i in page["Items"]
                 if i["sk"].startswith(("SEARCH#", "SAVED#", "FEEDBACK#", "VISIT#"))]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    counts = {p: sum(k["sk"].startswith(p) for k in keys) for p in ("SEARCH#", "SAVED#", "FEEDBACK#", "VISIT#")}
    print(f"Table {name}: {counts}", file=sys.stderr)
    if not args.yes:
        print("Dry run. Pass --yes to delete.", file=sys.stderr)
        return
    with table.batch_writer() as batch:
        for key in keys:
            batch.delete_item(Key=key)
    print(f"Deleted {len(keys)} items.", file=sys.stderr)


if __name__ == "__main__":
    main()
