---
type: investigation
tags: [evomem, search, bm25, rrf, embeddings, hybrid-retrieval, rust, sqlite, latency, multilingual]
created: 2026-11-06
last_verified: 2026-11-06
status: current: recommendations only, nothing implemented; no Indonesian or chat-transcript benchmark was found, so every quality claim needs a local eval first
---

# Which search algorithm would suit evomem better? (web research + code reading)

Question: "what search algorithm is better for our evomem?" Context: [evomem-mcp-failures-diagnosis.md](evomem-mcp-failures-diagnosis.md) (cold search 11.5 s) and [evomem-utcp-endpoint-fork-and-deploy.md](evomem-utcp-endpoint-fork-and-deploy.md).

## What evomem does today (read from `txtsamu/evomem` branch `feat/utcp`)

Command used: `cat src/search/{mod,vector,fusion,lexical}.rs src/embed/*.rs src/config.rs`.

| Stage | Implementation |
|---|---|
| Chunking | Markdown headings, target 1200 chars / max 2000, heading path kept |
| Lexical | Own "EvoRank" bucket sort (Meilisearch style): words matched, IDF, typo/stem cost, proximity, attribute, exactness. Query words resolved against a vocabulary with bounded Levenshtein. **Not BM25** |
| Vector | `HashEmbedder`, id `hash-v1-d512`: FNV-1a feature hashing of word tokens plus char 3/4-grams into 512 floats. Its own doc comment: "lexical smearing, not semantics". Brute-force cosine over every chunk, top 40 |
| Fusion | RRF, k = 60, weights 1.0-1.2 by intent, top 30 |
| After fusion | Graph augmentation, source-tier factor, authority prior (in-degree), recency prior, x1.4 title / x1.6 alias boost, dedup by doc, token budget |
| Storage | One SQLite file: `chunks` 215 MB (text and embedding in the same row), `word_index` 207 MB + index 201 MB |
| Scale | 1184 docs, 51 466 chunks, 137 707 indexed words; mixed Indonesian and English; 859 of the docs are chat-session transcripts |

Two consequences:
1. The "vector" half has no real semantic knowledge, so today's hybrid is two lexical signals fused. A query like "why is the NAS flaky" cannot find "iSCSI ping timeout" unless words overlap.
2. Every search scans the whole `chunks` table (embedding blobs are interleaved with chunk text) plus the postings, which is the cold-cache cost measured in the diagnosis doc.

## Findings from the research (each with its source)

1. **Fusion: tuned convex combination beats RRF.** Bruch et al. compare a convex combination of normalized scores with RRF and report CC wins in-domain and out-of-domain, needs only a few labelled queries to tune its single weight, while a tuned RRF generalizes poorly out of domain. evomem uses RRF k=60 plus many hand-set multipliers.
2. **Contextual retrieval.** Anthropic reports failed retrievals (top-20) falling 5.7 % to 3.7 % with contextual embeddings, 2.9 % adding contextual BM25 (49 % fewer failures), and 67 % fewer with reranking. Context = 50-100 tokens of chunk-specific explanation prepended before embedding and before building the keyword index. Their numbers, their datasets; a commentary piece argues teams already running hybrid + rerank would see less.
3. **Brute force is fine at this size.** Sources: a Pi 4 scan of 50 000 x 128-d float32 vectors takes about 8 ms; a sqlite-vec flat scan at 50k is usually faster than HNSW; brute force is suggested below roughly 100k vectors. HNSW only pays at 500k+ vectors. The issue in evomem is I/O layout, not the algorithm.
4. **Quantization.** int8 scalar quantization: about 1-3 % retrieval loss, 4x smaller, no rescoring. Binary needs 768+ dims and rescoring and is built for millions of vectors, so it is not worth it here.
5. **Embedding models for Indonesian + English on CPU.** Qdrant publishes an ONNX Qwen3-Embedding-0.6B for FastEmbed: 1024-d, 100+ languages, 32K context, int8 about 1.1 GB vs 2.4 GB fp32 (cosine 0.9997 vs fp32 in the authors' sample); Qwen's own table lists 64.33 (English MTEB avg) vs BGE-M3 59.56. Smaller options named: bge-small / e5-small (efficiency), EmbeddingGemma-300M (anecdotal "fast on CPU"), static model2vec-style models (very fast, lower quality). **No source benchmarked Indonesian retrieval or multilingual-e5-small.**
6. **Rust tooling.** fastembed-rs runs ONNX locally (dense `TextEmbedding`, SPLADE sparse, BGE-M3 dense+sparse+ColBERT, cross-encoder `TextRerank`), models download once, then offline. Version numbers differed between sources (5.17.2, 6.0.0, 6.0.3): check crates.io before pinning. Nothing verified about tantivy/usearch from this search.
7. **Bucket sort vs BM25.** Meilisearch's own docs say bucket sort is optimized for app/site search and that BM25 may suit some scenarios; they do not say which. Nothing found on long documents or chat transcripts. BM25's term-frequency saturation and length normalization are the usual reasons to prefer it for long text (general knowledge, not from these sources).

## Recommendation (ordered, nothing implemented yet)

| # | Change | Why | Cost / risk |
|---|---|---|---|
| 0 | Hold all chunk embeddings in process memory (load at start, update on capture/sync); optionally int8 | Removes the vector half's disk scan: 51 466 x 512 x 4 B = 105 MB f32 (about 26 MB int8). Fixes the cold-start tail without changing results (f32) | Small Rust change in `vector.rs`/`store`; also warm `word_index` postings (timer or MemoryLow) |
| 1 | Build an eval set first: about 70 real queries are in the MCP logs (67 successful `evomem_search` calls plus 9 failed) | Without labels, none of #2-#5 can be judged; both papers say tune on a small labelled set | A few hours of labelling top-10 results |
| 2 | Real multilingual embeddings behind the existing `Embedder` trait (ONNX via fastembed-rs, or HTTP to Ollama/llama.cpp) | Gives the vector half actual semantics; the biggest expected quality gain | Re-embed 51k chunks once (my estimate: tens of minutes for a small model, possibly hours for a 0.6B model on home's Ryzen 7 2700, 8 cores, AVX2 only, 15 GiB RAM shared with k3s); `meta` embedder id prevents mixing vectors. Pick the model with the eval set from #1 |
| 3 | Replace RRF with min-max or z-score normalized convex combination, tune the weight on the eval set | Paper result above | Small; keep RRF as a switch |
| 4 | Deterministic context prefix per chunk (title, source, date, heading path) before embedding and indexing | Cheap version of contextual retrieval; LLM-written context for 51k chunks is not worth it first | Needs re-index |
| 5 | Optional cross-encoder rerank of the top 30 | Largest single drop in Anthropic's numbers | Adds CPU latency per query on home; measure first |
| 6 | Try adding BM25 as a third ranked list next to bucket sort; decide on the eval set | Bucket sort lacks length normalization on long chat chunks (unproven here) | Medium |

Not recommended now: HNSW / sqlite-vec index (corpus too small), binary quantization, SPLADE / ColBERT multi-vector (heavier, no evidence it pays at 50k chunks).

## Caveats

Most sources are blogs, vendor docs, and secondary write-ups; the two primary ones are the Bruch et al. paper and Anthropic's post. No source covers Indonesian, mixed-language chat transcripts, or this exact scale. Treat the plan as hypotheses to test on the eval set from step 1.

## References

- Bruch, Gai, Ingber, [An Analysis of Fusion Functions for Hybrid Retrieval](https://arxiv.org/abs/2210.11934)
- Anthropic, [Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval) (and the [research post](https://anthropic.com/research/contextual-retrieval))
- [Qwen3-Embedding-0.6B ONNX (Qdrant)](https://huggingface.co/Qdrant/Qwen3-Embedding-0.6B-onnx)
- [fastembed-rs docs](https://docs.rs/fastembed/=6.0.3/)
- [Vector DB vs brute force, the 50 ms rule](https://kubaik.github.io/vector-db-vs-brute-force-the-50ms-rule/) and [local WASM vector benchmarks](https://ninadpathak.pages.dev/blog/local-wasm-vector-benchmarks/)
- [Embedding quantization (sbert.net)](https://sbert.net/examples/applications/embedding-quantization/README.html) and [Scalar quantization](https://frutik.github.io/awesome-search/Concepts/Scalar-Quantization)
- [Meilisearch ranking rules / bucket sort](https://www.meilisearch.com/docs/resources/internals/bucket_sort)
- [Hybrid RAG in 200 lines: SQLite FTS5 + sqlite-vec + RRF](https://dev.to/soytuber/building-a-hybrid-rag-in-200-lines-sqlite-fts5-sqlite-vec-rrf-38h1)
- [Best local embedding models for RAG (2026)](https://d-central.tech/local-embedding-models/)
