# Master Execution Plan: Discord Multimodal RAG Project

## Project Overview
Enhance the Discord Multimodal RAG system with multi-turn conversation memory in threads/replies (R1), extended document parsing (.docx, .xlsx, .pptx, .csv, .md, code files) & Qdrant indexing (R2), verify <3s slash command deferrals, and execute clean git workflow & VPS deployment.

## Milestones Breakdown

### Phase 1: Exploration & Architecture Assessment
- **Task 1.1**: Dispatch Explorer subagent to inspect existing codebase (`bot.py`, `config.py`, `cogs/`, `services/`, dependencies in `requirements.txt`, Qdrant / Chroma setups).
- **Task 1.2**: Generate `PROJECT.md` capturing codebase layout, data flows, and module contracts.

### Phase 2: Milestone 1 - Conversation Memory & Thread Support (R1)
- **Task 2.1**: Dispatch Explorer to formulate detailed implementation design for context tracking (last 5 turns) in Discord threads and reply chains.
- **Task 2.2**: Dispatch Worker to implement conversation context store / buffer (e.g. per-thread/reply message history window of 5 turns) and integrate into RAG Q&A query pipeline.
- **Task 2.3**: Dispatch Reviewer & Challenger to verify context retention (e.g. asking follow-up question "Peux-tu détailler le point 2 ?" works seamlessly).
- **Task 2.4**: Dispatch Forensic Auditor for integrity check.

### Phase 3: Milestone 2 - Extended Document Format Support & Indexing (R2)
- **Task 3.1**: Dispatch Explorer to design parsers for `.docx`, `.xlsx`, `.pptx`, `.csv`, `.md`, and code files (`.py`, `.js`, `.json`, `.html`, `.css`) and Qdrant ingestion schema.
- **Task 3.2**: Dispatch Worker to implement parser modules (using `python-docx`, `openpyxl`, `python-pptx`, `pandas`/`csv`, code text loaders, etc.) and integrate with Qdrant vector store indexing.
- **Task 3.3**: Dispatch Reviewer & Challenger to verify parsing and Qdrant indexing across all new formats.
- **Task 3.4**: Dispatch Forensic Auditor for integrity check.

### Phase 4: Milestone 3 - Performance, End-to-End Verification, Git Workflow & VPS Deployment
- **Task 4.1**: Dispatch Explorer/Worker to inspect all slash commands for `defer()` response timing (< 3s guarantee).
- **Task 4.2**: Run E2E test verification suite.
- **Task 4.3**: Dispatch Worker to execute Git workflow (commit & push to repository) and trigger/verify VPS deployment.
- **Task 4.4**: Dispatch Forensic Auditor for final integrity check.
- **Task 4.5**: Synthesize final results and produce `handoff.md`.

## Quality & Integrity Controls
- All work dispatched to subagents.
- Mandatory Forensic Auditor check after implementation milestones.
- Strict requirement compliance: 5-turn thread memory, 10 extended doc formats + code files, 3s deferral limit, zero hardcoded/fake tests.
