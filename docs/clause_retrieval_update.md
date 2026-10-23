# Clause retrieval update — 2026-10-23

The active indexer now previews by default and updates a separate v2 Chroma collection with --apply. It retains the original 496 generic chunks and adds 13 complete, reviewed records. Generated bullet ordinals are explicitly distinguished from numbering actually printed in the handbook. Source text is preserved, including the inconsistent cross-reference in section 5.6.

Retrieval combines lexical ranking and vector ranking using reciprocal rank fusion. Among ranked candidates it prefers reviewed clauses that share query terms, expands linked section evidence, and returns no more than four passage groups. This preference is a pilot heuristic, not a proven general relevance model. Whole-source coverage remains available through the generic chunks. Unknown section/chapter metadata is never filled by a page-offset guess.

The search tool remains compatible with the existing workflow's string evidence field, now carrying JSON. The two additional tools can fetch a known clause and check a quote against an exact source-validated record. All returned citations include the quote, source offsets, page hash, title/version and metadata review flags. Parent context is checked against the extracted page before being returned.

Validation used the existing local Python environment and the real cached sentence-transformer model in a writable project copy. The existing database was copied there; the original project/database were not changed. The v2 collection contains 509 records; a repeat run reported 0 upserts and 509 unchanged. Seven focused retrieval cases and four integrity checks passed. The existing LangGraph attendance example completed with REVIEW_REQUIRED after one search. UTF-8 terminal output was enabled to print handbook bullet symbols correctly on Windows. This confirms compatibility, not claim-level verification.

Limitations: only the selected provisions have manually reviewed clause metadata. Lexical no-overlap abstention is not reliable out-of-corpus detection. Quote substring validation does not verify claim entailment or an academic recommendation. No new LLM agent, final assessment, API, queue, safety filter or operational feature is claimed. The course's full evaluation and operational requirements remain open.

