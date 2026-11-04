"""One live Retrieve against the parent guide's Bedrock Knowledge Base, with source documents (decision 028).

    AWS_PROFILE=gs-sandbox AWS_REGION=us-east-1 python agent/scripts/kb_demo.py "What is a charter school?"
    ... kb_demo.py --sync    # start an ingestion job, wait for it, then retrieve

Reads the knowledge base and data source ids from KNOWLEDGE_BASE_ID / DATA_SOURCE_ID or from
infra/cdk-outputs-knowledge.json (written by `cdk deploy GsKnowledgeStack --outputs-file ...`).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gs_agent import knowledge as K  # noqa: E402
from gs_agent import search  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def ids() -> tuple[str, str | None]:
    outputs_file = REPO / "infra" / "cdk-outputs-knowledge.json"
    outputs = json.loads(outputs_file.read_text())["GsKnowledgeStack"] if outputs_file.exists() else {}
    return (os.environ.get("KNOWLEDGE_BASE_ID") or outputs["KnowledgeBaseId"],
            os.environ.get("DATA_SOURCE_ID") or outputs.get("DataSourceId"))


def sync(agent, kb_id: str, ds_id: str) -> None:
    job = agent.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)["ingestionJob"]
    while job["status"] in ("STARTING", "IN_PROGRESS"):
        time.sleep(5)
        job = agent.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id,
                                      ingestionJobId=job["ingestionJobId"])["ingestionJob"]
    print(f"Ingestion job {job['ingestionJobId']}: {job['status']} {job.get('statistics', {})}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="?", default="What is a charter school?")
    parser.add_argument("--sync", action="store_true", help="run an ingestion job first and wait for it")
    args = parser.parse_args()

    kb_id, ds_id = ids()
    os.environ["KNOWLEDGE_BASE_ID"] = kb_id
    agent = boto3.Session(region_name=K.REGION).client("bedrock-agent")
    kb = agent.get_knowledge_base(knowledgeBaseId=kb_id)["knowledgeBase"]
    print(f"Knowledge base {kb_id} ({kb['name']}): {kb['status']}, "
          f"store {kb['storageConfiguration']['type']}")
    if ds_id:
        if args.sync:
            sync(agent, kb_id, ds_id)
        else:
            jobs = agent.list_ingestion_jobs(knowledgeBaseId=kb_id, dataSourceId=ds_id, maxResults=1,
                                             sortBy={"attribute": "STARTED_AT", "order": "DESCENDING"})
            for job in jobs["ingestionJobSummaries"]:
                print(f"Latest ingestion job {job['ingestionJobId']}: {job['status']} {job.get('statistics', {})}")

    print(f"\nRetrieve: {args.question!r}")
    raw = K._client().retrieve(knowledgeBaseId=kb_id, retrievalQuery={"text": args.question},
                               retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 5}})
    for r in raw["retrievalResults"]:
        print(f"  score {r['score']:.3f}  {r['location']['s3Location']['uri']}  ({r['metadata'].get('title')})")

    print(f"\nGuide entries the agent gets (cosine >= {K.MIN_SIMILARITY}, or title/alias in the question):")
    for e in search.lookup_content(args.question):
        print(f"  [{e['id']}] {e['title']}  (source document: {e['document']}, cosine {e['similarity']}"
              f"{', term match' if e['term_match'] else ''})")
        print(f"      {e['body'][:160]}{'…' if len(e['body']) > 160 else ''}")
        print(f"      {e['source']}")


if __name__ == "__main__":
    main()
