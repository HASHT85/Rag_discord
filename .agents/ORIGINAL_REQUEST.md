# Original User Request

## Initial Request — 2026-07-24T17:34:44Z

# Teamwork Project Prompt — Draft

An advanced, production-ready Discord Multimodal RAG system powered by Qdrant (3072d Dense + Sparse BM25 Hybrid Search), FlashRank Re-ranking, and Google Gemini 3.1 LLM.

Working directory: c:\Projet\Rag_discord
Integrity mode: development

## Requirements

### R1. Conversation Memory & Thread Support
- Implement multi-turn conversation memory for Q&A inside Discord threads/replies.
- Maintain the last 5 turns of conversation context when users ask follow-up questions in a thread.

### R2. Extended Document Format Support
- Add rich text extraction parsers for `.docx`, `.xlsx`, `.pptx`, `.csv`, `.md`, and code files (`.py`, `.js`, `.json`, `.html`, `.css`).
- Correctly index extracted text and code into Qdrant vectorstore with metadata.

## Acceptance Criteria

### Verification & Quality
- [ ] Asking a follow-up question in a Discord thread preserves previous context (e.g. "Peux-tu détailler le point 2 ?").
- [ ] Uploading `.docx`, `.xlsx`, `.pptx`, `.csv`, or `.py` files via `/doc` or channel indexing successfully extracts text and indexes it in Qdrant.
- [ ] All slash commands defer responses within 3 seconds to avoid Discord interaction timeouts.
- [ ] Git workflow (commit & push) and VPS deployment complete cleanly.
