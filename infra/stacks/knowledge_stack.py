import hashlib
import json
import tempfile
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_s3vectors as s3vectors,
    custom_resources as cr,
)
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE = REPO_ROOT / "data" / "content" / "guide.json"
SOURCE_LABEL = "GreatSchools guide (team-written summary for this demo)"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
EMBED_DIMS = 1024


def guide_documents(entries: list[dict]) -> dict[str, str]:
    """One markdown file per guide entry, plus its .metadata.json sidecar (key -> content).

    The title and aliases are in the text so the embedding matches the words parents use;
    agent/gs_agent/knowledge.py strips them again to get the body.
    """
    files = {}
    for e in entries:
        text = f"# {e['title']}\n\nAlso called: {', '.join(e['aliases'])}.\n\n{e['body']}\n"
        files[f"guide/{e['id']}.md"] = text
        files[f"guide/{e['id']}.md.metadata.json"] = json.dumps({"metadataAttributes": {
            "id": e["id"], "title": e["title"], "kind": e["kind"], "source": SOURCE_LABEL}})
    return files


class KnowledgeStack(Stack):
    """The parent guide as an Amazon Bedrock Knowledge Base on Amazon S3 Vectors (decision 028).

    Standalone: it exports nothing, so it can be deployed or destroyed without touching the
    data or app stacks. The app stack gets the knowledge base id as CDK context.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # The documents: data/content/guide.json, one file per entry with a metadata sidecar
        docs_bucket = s3.Bucket(self, "GuideDocsBucket", block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                                enforce_ssl=True, removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True)
        entries = json.loads(GUIDE.read_text(encoding="utf-8"))
        # Changes when an entry changes, whatever the file's line endings: re-runs ingestion
        guide_hash = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()[:16]
        # Written to a folder at synth time and uploaded as one asset (its hash follows the content)
        folder = Path(tempfile.mkdtemp(prefix="gs-guide-docs-"))
        for key, content in guide_documents(entries).items():
            (folder / key).parent.mkdir(parents=True, exist_ok=True)
            (folder / key).write_text(content, encoding="utf-8", newline="\n")
        upload = s3deploy.BucketDeployment(
            self, "GuideDocs", destination_bucket=docs_bucket, prune=True,
            sources=[s3deploy.Source.asset(str(folder))])

        # The vector store: S3 Vectors, the cheapest store a knowledge base can use (pay per GB
        # stored and per query, nothing while idle). Bedrock's own text and metadata fields are
        # non-filterable, so they don't count against the small filterable-metadata limit.
        vector_bucket = s3vectors.CfnVectorBucket(self, "GuideVectorBucket")
        index = s3vectors.CfnIndex(
            self, "GuideVectorIndex", vector_bucket_arn=vector_bucket.attr_vector_bucket_arn,
            index_name="parent-guide", data_type="float32", dimension=EMBED_DIMS, distance_metric="cosine",
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]))

        embed_arn = f"arn:aws:bedrock:{self.region}::foundation-model/{EMBED_MODEL}"
        kb_role = iam.Role(self, "KnowledgeBaseRole", assumed_by=iam.ServicePrincipal(
            "bedrock.amazonaws.com", conditions={"StringEquals": {"aws:SourceAccount": self.account}}))
        kb_role.add_to_policy(iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=[embed_arn]))
        docs_bucket.grant_read(kb_role)
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
                     "s3vectors:QueryVectors", "s3vectors:GetIndex"],
            resources=[index.attr_index_arn]))

        kb = bedrock.CfnKnowledgeBase(
            self, "GuideKnowledgeBase", name="greatschools-parent-guide", role_arn=kb_role.role_arn,
            description="GreatSchools parent guide: terms, how ratings work, how the app works (synthetic)",
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=embed_arn,
                    embedding_model_configuration=bedrock.CfnKnowledgeBase.EmbeddingModelConfigurationProperty(
                        bedrock_embedding_model_configuration=bedrock.CfnKnowledgeBase.BedrockEmbeddingModelConfigurationProperty(
                            dimensions=EMBED_DIMS, embedding_data_type="FLOAT32")))),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    index_arn=index.attr_index_arn)))
        kb.node.add_dependency(kb_role)

        # Entries are a few sentences each: one chunk per entry, so a hit is a whole entry
        source = bedrock.CfnDataSource(
            self, "GuideDataSource", knowledge_base_id=kb.attr_knowledge_base_id, name="parent-guide-s3",
            data_deletion_policy="DELETE",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3", s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=docs_bucket.bucket_arn, inclusion_prefixes=["guide/"])),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(chunking_strategy="NONE")))

        # Sync after every deploy that changes the guide: starts an ingestion job (it runs for
        # under a minute; agent/scripts/kb_demo.py shows the latest job's status).
        ingest_call = cr.AwsSdkCall(
            service="bedrock-agent", action="StartIngestionJob",
            parameters={"knowledgeBaseId": kb.attr_knowledge_base_id, "dataSourceId": source.attr_data_source_id},
            physical_resource_id=cr.PhysicalResourceId.of(guide_hash))
        ingest = cr.AwsCustomResource(
            self, "GuideIngestion", on_create=ingest_call, on_update=ingest_call, install_latest_aws_sdk=False,
            policy=cr.AwsCustomResourcePolicy.from_statements([iam.PolicyStatement(
                actions=["bedrock:StartIngestionJob"], resources=[kb.attr_knowledge_base_arn])]))
        ingest.node.add_dependency(upload)
        ingest.node.add_dependency(source)

        CfnOutput(self, "KnowledgeBaseId", value=kb.attr_knowledge_base_id)
        CfnOutput(self, "DataSourceId", value=source.attr_data_source_id)
        CfnOutput(self, "GuideDocsBucketName", value=docs_bucket.bucket_name)
        CfnOutput(self, "VectorIndexArn", value=index.attr_index_arn)
