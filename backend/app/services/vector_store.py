from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any
from app.core.config import get_settings


@dataclass
class VectorHit:
    id: str
    score: float
    metadata: dict[str, Any]


class VectorStore:
    _vectors: dict[str, tuple[list[float], dict[str, Any]]] = {}

    def __init__(self):
        self.settings = get_settings()
        self.client = None
        try:
            from pymilvus import MilvusClient
            self.client = MilvusClient(uri=self.settings.milvus_uri)
        except Exception:
            if self.settings.require_milvus or self.settings.environment.lower() in {"production", "staging"}:
                raise

    def ensure_collection(self) -> None:
        if not self.client:
            return
        from pymilvus import DataType, MilvusClient
        if self.client.has_collection(self.settings.milvus_collection):
            return
        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("id", DataType.VARCHAR, max_length=36, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.settings.embedding_dimension)
        index = self.client.prepare_index_params()
        index.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        self.client.create_collection(self.settings.milvus_collection, schema=schema, index_params=index)

    def upsert(self, values: list[dict[str, Any]]) -> None:
        if not values:
            return
        if self.client:
            self.ensure_collection()
            self.client.upsert(collection_name=self.settings.milvus_collection, data=values)
        else:
            for value in values:
                self._vectors[value["id"]] = (value["vector"], {k: v for k, v in value.items() if k not in {"id", "vector"}})

    def delete(self, ids: list[str]) -> None:
        if self.client and ids:
            self.client.delete(collection_name=self.settings.milvus_collection, ids=ids)
        for item in ids:
            self._vectors.pop(item, None)

    def search(self, vector: list[float], workspace_id: str, kb_id: str, top_k: int = 20) -> list[VectorHit]:
        if self.client:
            self.ensure_collection()
            result = self.client.search(collection_name=self.settings.milvus_collection, data=[vector], limit=top_k, filter=f'workspace_id == "{workspace_id}" and knowledge_base_id == "{kb_id}"', output_fields=["*"])
            return [VectorHit(str(hit["id"]), float(hit["distance"]), {k: v for k, v in hit.items() if k not in {"id", "distance"}}) for hit in (result[0] if result else [])]
        scored: list[VectorHit] = []
        for item_id, (candidate, metadata) in self._vectors.items():
            if metadata.get("workspace_id") != workspace_id or metadata.get("knowledge_base_id") != kb_id:
                continue
            score = sum(a * b for a, b in zip(vector, candidate)) / ((math.sqrt(sum(a * a for a in vector)) or 1) * (math.sqrt(sum(a * a for a in candidate)) or 1))
            scored.append(VectorHit(item_id, score, metadata))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]
