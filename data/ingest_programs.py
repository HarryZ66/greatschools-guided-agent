"""Load program documents (library and community events) into OpenSearch with a Titan embedding each.

    AWS_PROFILE=gs-sandbox .venv/bin/python data/ingest_programs.py \
        data/raw/programs_sample.json data/generated/programs_generated.json --recreate
"""

import argparse
import json
import sys
from pathlib import Path

import boto3
from opensearchpy import helpers

from ingest import EMBED_DIMS, REGION, embed, opensearch_client

INDEX = "programs"

MAPPING = {
    "settings": {"index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0}},
    "mappings": {
        "dynamic_templates": [{"strings_as_keywords": {"match_mapping_type": "string",
                                                       "mapping": {"type": "keyword", "ignore_above": 256}}}],
        "properties": {
            "name": {"type": "text", "analyzer": "english", "fields": {"raw": {"type": "keyword"}}},
            "description": {"type": "text", "analyzer": "english"},
            "location": {"type": "geo_point"},
            "age_min_search": {"type": "integer"},
            "age_max_search": {"type": "integer"},
            "upcoming_instance_count": {"type": "integer"},
            "next_start_date": {"type": "date"},
            # Kept for evidence, not searched
            "instances": {"type": "object", "enabled": False},
            "organizations": {"type": "object", "enabled": False},
            "vector": {"type": "knn_vector", "dimension": EMBED_DIMS,
                       "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"}},
        },
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()

    session = boto3.Session(region_name=REGION)
    client = opensearch_client(session)
    bedrock = session.client("bedrock-runtime")
    if args.recreate and client.indices.exists(index=INDEX):
        client.indices.delete(index=INDEX)
    if not client.indices.exists(index=INDEX):
        client.indices.create(index=INDEX, body=MAPPING)

    programs = [p for path in args.files for p in json.loads(path.read_text())]
    actions = []
    for p in programs:
        lat, lon = (float(v) for v in p["latlon"].split(","))
        text = f"{p['name']}. {', '.join(p['tag_names'])}. {p['description']}"
        doc = {**p, "location": {"lat": lat, "lon": lon}, "vector": embed(bedrock, text)}
        actions.append({"_index": INDEX, "_id": p["id"].removeprefix("Program "), "_source": doc})
    ok, errors = helpers.bulk(client, actions, raise_on_error=False)
    client.indices.refresh(index=INDEX)
    print(f"Indexed {ok} programs into '{INDEX}'; {len(errors)} errors", file=sys.stderr)
    for e in errors[:3]:
        print(json.dumps(e)[:400], file=sys.stderr)


if __name__ == "__main__":
    main()
