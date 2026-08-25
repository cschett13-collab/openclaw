# RAG architectures reference

## Hybrid RAG

Hybrid RAG combines dense and sparse retrieval. Dense retrieval embeds the query
with an embedding model and searches a vector database for semantically similar
chunks. Sparse retrieval uses a BM25 keyword index to catch exact term matches.
The two result lists are merged with Reciprocal Rank Fusion, the top-K chunks are
selected, and a language model produces the answer. Hybrid RAG is the recommended
default because it captures both semantic meaning and exact keywords.

## GraphRAG

GraphRAG extracts entities and the relationships between them into a knowledge
graph, where nodes are entities and edges are relationships. At query time it
retrieves relevant subgraphs and community summaries before calling the language
model. GraphRAG is the best choice when the answer lives in the relationships
between things, such as how a person is connected to a project or a company.

## Agentic RAG

Agentic RAG turns retrieval into a multi-step plan instead of a single step. A
planner agent decides which tools to call, such as vector search, web search, or
a SQL database, and a reasoner agent loops until it is confident in the answer.
Agentic RAG is the most flexible and the most expensive pattern, and it suits
questions that need reasoning over multiple sources.

## Corrective RAG

Corrective RAG, also called CRAG, grades retrieved documents before trusting
them. An evaluator scores each retrieved chunk. If a chunk is correct it goes to
the language model, if it is ambiguous the query is rewritten and retrieval runs
again, and if it is incorrect the system falls back to a web search. CRAG adds a
quality gate that reduces hallucination when accuracy matters.

## Multimodal RAG

Multimodal RAG builds a single shared embedding space over text, images, charts,
and tables using a multimodal embedding model such as CLIP or ColPali. Everything
goes into one unified vector index, retrieval runs across all modalities, and a
multimodal language model that understands both vision and text produces the
answer. Multimodal RAG suits documents whose information is not purely text.
