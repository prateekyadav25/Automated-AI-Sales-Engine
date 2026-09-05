# RAG Architecture

```mermaid
flowchart TD
  Upload --> Parse
  Parse --> Chunk
  Chunk --> Metadata
  Metadata --> Embed
  Embed --> VectorIndex
  Query --> HybridRetrieve
  HybridRetrieve --> PermissionFilter
  PermissionFilter --> Rerank
  Rerank --> LLM
  LLM --> Citations
```

Chunks store `tenant_id`, source id, ordinal, text, embedding, metadata. Retrieval is tenant-scoped. Answers must cite chunk ids or abstain. LLM never sees another tenant's chunks.
