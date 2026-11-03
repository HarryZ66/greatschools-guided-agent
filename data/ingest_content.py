"""Load the parent guide (terms, ratings framework, how the app works) into OpenSearch.

    AWS_PROFILE=gs-sandbox .venv/bin/python data/ingest_content.py data/content/guide.json --recreate

Entries are short summaries written by the team; see each entry's "kind".
"""

import argparse
import json
import sys
from pathlib import Path

import boto3
from opensearchpy import helpers

from ingest import EMBED_DIMS, REGION, embed, opensearch_client

INDEX = "content"
SOURCE_LABEL = "GreatSchools guide (team-written summary for this demo)"

MAPPING = {
    "settings": {"index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0}},
    "mappings": {"properties": {
        "kind": {"type": "keyword"},
        # English analyzer: drops stop words ("what", "is") and stems ("lotteries" -> "lottery")
        "title": {"type": "text", "analyzer": "english", "fields": {"raw": {"type": "keyword"}}},
        "aliases": {"type": "text", "analyzer": "english"},
        "body": {"type": "text", "analyzer": "english"},
        "source": {"type": "keyword"},
        "vector": {"type": "knn_vector", "dimension": EMBED_DIMS,
                   "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"}},
    }},
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path)
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()

    session = boto3.Session(region_name=REGION)
    client = opensearch_client(session)
    bedrock = session.client("bedrock-runtime")
    if args.recreate and client.indices.exists(index=INDEX):
        client.indices.delete(index=INDEX)
    if not client.indices.exists(index=INDEX):
        client.indices.create(index=INDEX, body=MAPPING)

    entries = json.loads(args.file.read_text())
    actions = []
    for entry in entries:
        text = f"{entry['title']}. Also called: {', '.join(entry['aliases'])}. {entry['body']}"
        actions.append({"_index": INDEX, "_id": entry["id"], "_source": {
            **entry, "source": SOURCE_LABEL, "vector": embed(bedrock, text)}})
        print(f"  {entry['id']}", file=sys.stderr)
    ok, errors = helpers.bulk(client, actions, raise_on_error=False)
    client.indices.refresh(index=INDEX)
    print(f"Indexed {ok} entries into '{INDEX}'; {len(errors)} errors")


if __name__ == "__main__":
    main()
