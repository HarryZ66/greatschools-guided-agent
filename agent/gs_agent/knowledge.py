"""The parent guide from an Amazon Bedrock Knowledge Base (decision 028).

With KNOWLEDGE_BASE_ID set, guide lookups call the Bedrock Agent Runtime Retrieve API instead of
OpenSearch. Each guide entry is one document in S3 (infra/stacks/knowledge_stack.py) with its id,
title, kind and source in a metadata sidecar, so a hit maps back to the entry and names the
document it came from. Without KNOWLEDGE_BASE_ID nothing here runs.
"""

import os
import re
from functools import lru_cache

import boto3

from .config import REGION

SERVICE = "Amazon Bedrock Knowledge Base"
# Retrieve scores a cosine index as (1 + cosine) / 2 (checked against Titan embeddings). The
# guide keeps OpenSearch's rule: a hit is relevant if its cosine similarity is at least this, or
# its title or an alias is in the question (exact terms like "CTE").
MIN_SIMILARITY = 0.35


def knowledge_base_id() -> str | None:
    return os.environ.get("KNOWLEDGE_BASE_ID") or None


def enabled() -> bool:
    return bool(knowledge_base_id())


@lru_cache(maxsize=1)
def _client():
    return boto3.Session(region_name=REGION).client("bedrock-agent-runtime")


def _aliases(text: str) -> list[str]:
    for line in text.splitlines():
        if line.startswith("Also called:"):
            return [a.strip() for a in line.removeprefix("Also called:").strip().rstrip(".").split(",") if a.strip()]
    return []


def _term_match(question: str, names: list[str], everyday: frozenset[str]) -> bool:
    q = question.lower()
    return any(re.search(rf"\b{re.escape(n.lower())}s?\b", q) for n in names if n.lower() not in everyday)


def _body(text: str) -> str:
    """The entry's body: the document without its title line and "Also called" line."""
    keep = [p.strip() for p in text.strip().split("\n\n")
            if p.strip() and not p.lstrip().startswith("# ") and not p.lstrip().startswith("Also called:")]
    return "\n\n".join(keep) or text.strip()


def entry(result: dict, question: str = "", everyday: frozenset[str] = frozenset()) -> dict | None:
    """One Retrieve result as a guide entry, or None if it lacks the entry's metadata."""
    meta = result.get("metadata") or {}
    if not meta.get("id"):
        return None
    text = result.get("content", {}).get("text", "")
    title = meta.get("title", meta["id"])
    uri = (result.get("location") or {}).get("s3Location", {}).get("uri") or meta.get("x-amz-bedrock-kb-source-uri", "")
    return {
        "id": meta["id"],
        "kind": meta.get("kind"),
        "title": title,
        "body": _body(text),
        "source": meta.get("source"),
        "document": uri.rsplit("/", 1)[-1],
        "uri": uri,
        "similarity": round(2 * float(result.get("score") or 0) - 1, 3),
        "term_match": _term_match(question, [title, *_aliases(text)], everyday),
    }


def lookup(question: str, k: int = 3, everyday: frozenset[str] = frozenset()) -> list[dict]:
    """Relevant guide entries for a question, best first. Unrelated questions return nothing.

    `everyday` words (too common in school questions) never count as a term match on their own.
    """
    response = _client().retrieve(
        knowledgeBaseId=knowledge_base_id(), retrievalQuery={"text": question},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 8}})
    entries: dict[str, dict] = {}
    for result in response.get("retrievalResults", []):
        e = entry(result, question, everyday)
        if e and (e["term_match"] or e["similarity"] >= MIN_SIMILARITY) and e["id"] not in entries:
            entries[e["id"]] = e
    return sorted(entries.values(), key=lambda e: e["similarity"] + (0.5 if e["term_match"] else 0), reverse=True)[:k]
