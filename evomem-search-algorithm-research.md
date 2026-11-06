---
type: investigation
tags: [evomem, search, bm25, rrf, embeddings, hybrid-retrieval, rust, sqlite, latency, multilingual]
created: 2026-11-06
last_verified: 2026-11-06
status: current: recommendations only, nothing implemented; no Indonesian or chat-transcript benchmark was found, so every quality claim needs a local eval first
---

# Which search algorithm would suit evomem better? (web research + code reading)

Question: "what search algorithm is better for our evomem?" Context: [evomem-mcp-failures-diagnosis.md](evomem-mcp-failures-diagnosis.md) (cold search 11.5 s) and [evomem-utcp-endpoint-fork-and-deploy.md](evomem-utcp-endpoint-fork-and-deploy.md).

## What the author says, and what he seems to have intended

Sources read: upstream `anvie/evomem` README, source comments, commit messages (`git log origin/main`, 18 commits, 2026-06-20 to 2026-07-20). The author never writes a design-rationale document; the reasons below are his stated goals plus my inference.

Stated by the author:
- README: a directory of markdown files turned into a queryable "knowledge", "inspired by gbrain and Obsidian", combining lexical search, hash-based vector embeddings and typed knowledge graphs "with zero LLM dependency at query time", "without the cost, latency, or unpredictability of calling an LLM for every retrieval". Everything is deterministic; "the design is minimal by choice"; 8 MB binary, no runtime dependencies. Benchmarks go up to 1 000 pages / 26 MB (about 42 ms per search).
- `lexical.rs`: bucket sort chosen over BM25 for deterministic, explainable ranking; "no FTS5/BM25" (`schema.rs`).
- `hash_embedder.rs`: "lexical smearing, not semantics ... swap in a real model via the Embedder trait when semantic recall matters". `vector.rs`: brute force "fine to ~50K chunks; swap for an HNSW index if needed".
- `config.rs` `SourceTiers`: curated dirs (`originals`, `concepts`, `writing`) boosted x1.3; bulk dirs (`chat` and `daily` x0.6, `media` x0.7, `archive` x0.5) demoted; `test`, `attachments`, `.raw` excluded.
- README says "BLAKE3-based hash embedding"; the code uses FNV-1a (README is wrong).

Inferred intent: a small, curated, human-readable notebook for an agent (entities such as people and companies, concepts, writing, with typed links), where search is a precise lookup of named things and bulk chat is a low-priority fallback.

### How the author himself uses evomem: Evonic (anvie/evonic)

The same author's agent platform makes evomem its default "Memory Engine" (`EVONIC_MEMORY_ENGINE=evomem`, FTS5 fallback; README: "Hybrid semantic + knowledge graph search (Evomem) for long-term memory"). Sources: Evonic README (Knowledge Base / Memory sections), `backend/agent_runtime/{memory_manager,evomem_writer,evomem_client}.py`, `backend/evomem_provision.py` (downloads the binary from `anvie/evomem` releases), CHANGELOG.

- One evomem KB per agent. Raw conversations stay in Evonic's own SQLite DB; they are **not** indexed into evomem.
- Write path is LLM-curated: the summarizer extracts durable facts from each conversation (categories `user_info`, `preference`, `decision`, `context`, `instruction`), deduplicates them against existing memory with hybrid search, and stores them. A "KB Organizer" sub-agent extracts entities (person, place, organization, event), writes one doc per entity with inline `[[Doc Title]]` wiki-links, merges duplicates, and fixes dangling links. Writes are followed by a debounced `sync` (5 s).
- `type: session` / `type: group` in `evomem_writer.py` is the **index doc of a collection folder**, not a transcript. (Earlier in this doc I read the valid `session` type as the author expecting session logs; that was wrong. Our 1 128 docs with `type: session` are raw transcripts using the label for something else.)
- Query path stays cheap: passive injection uses `conservative` mode; explicit `recall` uses `tokenmax` with `EVOMEM_RECALL_MIN_SCORE=0.03`, with the code comment "maximum recall from the weak hash embedder" (this is the use case behind the upstream "minimum score filtering" commit).

So the design is: **spend the LLM at write time (extract, link, dedupe), keep retrieval deterministic and LLM-free**. The weak hash embedder is acceptable because documents are short, entity-centred and already normalized by an LLM. Indexing raw transcripts skips that curation step, which is why search over our KB behaves poorly.

## What our KB actually is (live data, 2026-11-06)

| Source dir | Docs | Chunks | Share of chunks |
|---|---|---|---|
| `claude/` (raw Claude Code transcripts, about 149 chunks per doc) | 269 | 40 065 | 78 % |
| `sessions/` (older session logs) | 859 | 10 959 | 21 % |
| `claude-research/` (curated write-ups) | 34 | 473 | 0.9 % |
| `inbox/` + `lessons/` | 22 | 41 | 0.1 % |

1 128 of 1 184 docs are `type: session`. Graph links: 1 525 auto "mentions" and 2 typed edges, 1 171 dangling. `claude/` and `sessions/` are not in the author's demote table, so they get factor 1.0: raw transcripts rank as equals of curated notes. The integration that fills the KB (hooks, backfill, `feat/claude-code-integration`) is our fork's work, not the author's.

Conclusion: evomem is being used as a long-term conversation archive, about 99 % raw transcript chunks, at 50x the size the author benchmarked. That is not forbidden (`capture` exists), but it is not what the design targets, and it explains the cold-cache cost (41k of 51k chunks are transcripts), noisy hits (top hits are often raw `{"session_id": ...}` JSON), and why the hash embedder feels weak.

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

**Revised after reading the author's intent and the corpus breakdown: fix what goes in before changing the algorithm.** The table below was written first and answers "which algorithm"; the corpus split above is the bigger lever.

| # | Content change (before any algorithm work) | Why |
|---|---|---|
| A | Add `claude` and `sessions` to `SourceTiers::DEMOTE` in the fork (for example 0.5-0.6, with the temporal exception) | One-line use of the author's own mechanism; curated notes stop competing with transcripts |
| B | Keep curated KB (`claude-research`, `lessons`, `inbox`, distilled one-note-per-session summaries of `type: session`) as the main index; move raw transcripts to a second evomem KB/instance or stop indexing them | Brings the main KB back to a few thousand chunks, inside the author's tested range (about 1 000 docs, 45 ms), shrinks the DB about 10x so the cold read mostly disappears, and makes the hash embedder adequate |
| C0 | Optionally add the author's write-time step: after a session, have an LLM distill durable facts/decisions/entities into short docs with `[[links]]` (Evonic's summarizer + KB Organizer pattern) and index those instead of the transcript | This is how evomem is meant to be fed |
| C | Decide whether searching raw history is the real need ("did we ever..."); if so keep it as the separate, demoted archive | That is episodic memory, a different job from a curated knowledge base |

After A-C, re-measure before doing the algorithm items below; embeddings, fusion and rerank matter much more on the 51k-chunk transcript archive than on a curated KB.


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
- [anvie/evonic](https://github.com/anvie/evonic) README and `backend/agent_runtime/memory_manager.py`, `evomem_writer.py` (how the author integrates evomem)
- [Hybrid RAG in 200 lines: SQLite FTS5 + sqlite-vec + RRF](https://dev.to/soytuber/building-a-hybrid-rag-in-200-lines-sqlite-fts5-sqlite-vec-rrf-38h1)
- [Best local embedding models for RAG (2026)](https://d-central.tech/local-embedding-models/)
