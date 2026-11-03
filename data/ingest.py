"""Load school documents into OpenSearch, with a Titan embedding per school.

Usage (from the repo root):
    AWS_PROFILE=gs-sandbox .venv/bin/python data/ingest.py data/raw/schools_sample.json --recreate

The OpenSearch endpoint is read from infra/cdk-outputs.json (written by `cdk deploy`),
or from the SEARCH_ENDPOINT environment variable.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection, helpers

REGION = "us-east-1"
INDEX = "schools"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
EMBED_DIMS = 1024
REPO_ROOT = Path(__file__).resolve().parent.parent

# Most string fields (city, osp values, tiers) are exact-match keywords.
# Free text that parents' words should match is mapped as text explicitly.
MAPPING = {
    "settings": {"index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0}},
    "mappings": {
        "dynamic_templates": [
            {"strings_as_keywords": {
                "match_mapping_type": "string",
                "mapping": {"type": "keyword", "ignore_above": 256},
            }},
        ],
        "properties": {
            "name": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "location": {"type": "geo_point"},
            "summary_rating": {"type": "integer"},
            "test_scores_rating": {"type": "integer"},
            "avg_review_rating": {"type": "float"},
            "student_teacher_ratio": {"type": "float"},
            "attendance_rate": {"type": "float"},
            "enrollment": {"type": "integer"},
            "esp_text": {"type": "text"},
            "reviews_text": {"type": "text"},
            "reviews_positive": {"type": "text"},
            "reviews_negative": {"type": "text"},
            "reviews_full": {
                "type": "nested",
                "properties": {
                    "text": {"type": "text"},
                    "created_date": {"type": "date"},
                    "overall_rating": {"type": "float"},
                },
            },
            "profile_text": {"type": "text"},
            "profile_vector": {
                "type": "knn_vector",
                "dimension": EMBED_DIMS,
                "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"},
            },
        },
    },
}


def search_endpoint() -> str:
    if os.environ.get("SEARCH_ENDPOINT"):
        return os.environ["SEARCH_ENDPOINT"]
    outputs = json.loads((REPO_ROOT / "infra" / "cdk-outputs.json").read_text())
    return outputs["GsDataStack"]["SearchEndpoint"]


def opensearch_client(session: boto3.Session) -> OpenSearch:
    host = search_endpoint().removeprefix("https://")
    return OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=AWSV4SignerAuth(session.get_credentials(), REGION, "es"),
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )


def profile_text(school: dict) -> str:
    """Text that represents what a school offers, used for semantic matching."""
    parts = [school.get("name", ""), school.get("entity_type", ""), school.get("city", "")]
    parts += school.get("esp_text", [])
    for key, values in school.get("osp", {}).items():
        if key.endswith(("_url", "_email", "_phone", "_fax", "_name")) or key == "address":
            continue
        parts.append(f"{key}: {', '.join(str(v) for v in values)}")
    parts += school.get("reviews_positive", [])[:2]
    return "\n".join(p for p in parts if p)


def to_document(school: dict) -> dict:
    doc = dict(school)
    lat, lon = (float(v) for v in school["latlon"].split(","))
    doc["location"] = {"lat": lat, "lon": lon}
    doc["profile_text"] = profile_text(school)
    return doc


def embed(bedrock, text: str) -> list[float]:
    body = json.dumps({"inputText": text[:20000], "dimensions": EMBED_DIMS, "normalize": True})
    response = bedrock.invoke_model(modelId=EMBED_MODEL, body=body)
    return json.loads(response["body"].read())["embedding"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path, help="JSON list of school documents")
    parser.add_argument("--recreate", action="store_true", help="delete and recreate the index first")
    args = parser.parse_args()

    session = boto3.Session(region_name=REGION)
    client = opensearch_client(session)
    bedrock = session.client("bedrock-runtime")

    if args.recreate and client.indices.exists(index=INDEX):
        client.indices.delete(index=INDEX)
    if not client.indices.exists(index=INDEX):
        client.indices.create(index=INDEX, body=MAPPING)

    schools = json.loads(args.file.read_text())
    actions = []
    for i, school in enumerate(schools, 1):
        doc = to_document(school)
        doc["profile_vector"] = embed(bedrock, doc["profile_text"])
        # "School fl-95390" -> "fl-95390", the id the API and UI use
        actions.append({"_index": INDEX, "_id": school["id"].removeprefix("School "), "_source": doc})
        print(f"  [{i}/{len(schools)}] {school['name']}", file=sys.stderr)

    ok, errors = helpers.bulk(client, actions, raise_on_error=False)
    client.indices.refresh(index=INDEX)
    print(f"Indexed {ok} documents into '{INDEX}'; {len(errors)} errors")
    for error in errors[:5]:
        print(json.dumps(error)[:500])


if __name__ == "__main__":
    main()
