# Codebase Analysis Report — Discord Multimodal RAG System

**Date**: 2026-07-24  
**Target Repository**: `c:\Projet\Rag_discord`  
**Agent**: Explorer (`teamwork_preview_explorer_arch_1`)  

---

## 1. Executive Summary & Architecture

The **Discord Multimodal RAG System** is a Discord bot built with `discord.py v2.x` designed to index server knowledge (text messages and attachments) into a vector database and answer user questions using Retrieval-Augmented Generation (RAG).

### Current Tech Stack
- **Bot Framework**: `discord.py >= 2.3.0`
- **Vector Database**: `Qdrant` (containerized, HTTP port `6333`, collection `discord_rag`)
- **Embedding Model**: `google/gemini-embedding-2-preview` (3072-dimensional dense embeddings via OpenRouter)
- **Sparse Search**: `fastembed` (`Qdrant/bm25` model for BM25 sparse vectors)
- **Search Strategy**: Qdrant Hybrid Search (Dense 3072d + Sparse BM25 with Reciprocal Rank Fusion)
- **Re-Ranking**: `FlashRank` (`ms-marco-TinyBERT-L-2-v2` lightweight cross-encoder reranker)
- **LLM / Vision**: `google/gemini-3.1-flash-lite` via OpenRouter (OpenAI-compatible client)
- **Document Extractors**: PyMuPDF (`fitz`) for PDF, UTF-8/Latin-1 text reader for plain text/code/json/csv/xml/yaml, Gemini Vision for images (.png, .jpg, .gif, .webp, .bmp).
- **Deployment**: Docker & Docker Compose (`discord-rag-bot-v2` + `qdrant-vectorstore`).

---

## 2. Component-by-Component Analysis

### 2.1 Entrypoint & Configuration
- **`bot.py`**:
  - Initializes `commands.Bot` with `command_prefix="!"` and intents `message_content=True`, `guilds=True`.
  - Loads three Cogs: `cogs.indexer`, `cogs.rag`, `cogs.admin`.
  - In `on_ready()`, copies global slash commands to each joined guild (`bot.tree.copy_global_to(guild=guild)`) and syncs locally (`bot.tree.sync(guild=guild)`).
  - Provides a prefix command `!sync <guild|global|clear>` for owner-initiated slash command synchronization.
- **`config.py`**:
  - Loads environment variables using `python-dotenv`.
  - Key constants: `LLM_MODEL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` (3072), `QDRANT_HOST`, `QDRANT_PORT`, `COLLECTION_NAME` ("discord_rag"), `TOP_K` (5), `CHUNK_SIZE` (500), `CHUNK_OVERLAP` (50).
  - Manages channel configuration persistence via `data/channels_config.json` (`load_channels_config`, `save_channels_config`).
- **`requirements.txt`**:
  - Contains `discord.py>=2.3.0`, `qdrant-client>=1.9.0`, `flashrank>=0.2.0`, `openai>=1.40.0`, `python-dotenv>=1.0.0`, `PyMuPDF>=1.24.0`, `aiohttp>=3.9.0`, `fastembed>=0.3.0`.
- **`docker-compose.yml` & `Dockerfile`**:
  - `Dockerfile`: `python:3.12-slim` base image, installs system packages (`git`, `ca-certificates`), installs `requirements.txt`, copies project files, runs `python bot.py`.
  - `docker-compose.yml`: Services `discord-rag-bot-v2` and `qdrant` (`qdrant/qdrant:latest`). Volumes map `./logs` and `./data`, with Qdrant storage mapped to `./data/qdrant_storage`.
- **Legacy Documentation Discrepancies**:
  - `README.md` and `.env.example` reference ChromaDB, Firestore, and 1536d embeddings. However, `config.py`, `services/vectorstore.py`, `requirements.txt`, and `docker-compose.yml` are fully transitioned to Qdrant + 3072d Gemini Embeddings + FlashRank.

---

## 3. Discord Commands & Message Listeners (Deferral Investigation)

### Slash Commands Deferral Status
Discord requires slash commands to respond or acknowledge within **3 seconds** (`3000ms`). Long-running commands must call `await interaction.response.defer(thinking=True)` to show a "thinking..." status and allow up to 15 minutes for `followup.send()`.

#### Audit of Slash Commands across Cogs:
1. **`cogs/admin.py`**:
   - `/setup`: Calls `await interaction.response.defer(thinking=True)` on line 65 before saving config and sending embeds. **DEFERRED PROPERLY**.
   - `/status`: Calls `await interaction.response.defer(thinking=True)` on line 134 before querying vectorstore stats. **DEFERRED PROPERLY**.
   - `/reindex`: Calls `await interaction.response.defer(thinking=True)` on line 216 before channel history traversal. **DEFERRED PROPERLY**.
   - `/help_format`: Calls `await interaction.response.send_message(...)` directly on line 413. Does **not** defer. (Acceptable since it only renders static text embeds without async I/O or vectorstore queries, but good practice is to keep responses fast).
2. **`cogs/indexer.py`**:
   - `/note`, `/doc`, `/procedure`, `/tuto`, `/info`: All route to `_index_info()`, which calls `await interaction.response.defer(thinking=True)` on line 170 before attachment downloading, chunking, embedding generation (OpenRouter API), and Qdrant insertion. **DEFERRED PROPERLY**.
3. **`cogs/rag.py`**:
   - `/ask`: Checks if interaction channel matches output channel (if restricted). If valid, calls `await interaction.response.defer(thinking=True)` on line 232 before running the full RAG pipeline (OpenRouter embedding -> Qdrant hybrid query -> FlashRank rerank -> LLM generation). **DEFERRED PROPERLY**.

### Message Listeners
1. **`cogs/indexer.py` (`on_message`)**:
   - Listens to messages in configured `input_channel_id`.
   - Ignores bots. Parses `[Category] Title` format via `parse_indexed_message`.
   - Downloads & parses attachments if present.
   - Embeds, chunks, and upserts into Qdrant. Adds reactions `✅` or `❌`/`⚠️`.
2. **`cogs/rag.py` (`on_message`)**:
   - Listens to messages in configured `output_channel_id`.
   - Ignores bots, messages starting with `!` or `/`, and messages under 3 characters.
   - Triggers `async with message.channel.typing():` while running `_run_rag_pipeline`.

---

## 4. Conversation History & Thread Support Analysis (R1)

### Current Implementation Assessment
- **Status**: **NOT IMPLEMENTED (0% present)**.
- **Findings**:
  - In `cogs/rag.py`, `/ask` and `on_message` treat every question in isolation.
  - Question processing only passes `question: str` (the current message text) to `_run_rag_pipeline`.
  - There is no checking if `message.channel` is a `discord.Thread` or if `message.reference` exists (reply to a message).
  - There is no conversation memory buffer service or data structure (e.g. `Turn`, `get_thread_context()`) to maintain the last 5 turns.
  - System prompt in `services/openrouter_client.py` (`generate_answer`) accepts only a single `question: str` and `context: str`. It has no message history parameter (`messages: list[dict]`).
- **Required Work for Milestone 2 (R1)**:
  - Create a conversation memory service (`services/memory.py` or similar) exposing `get_thread_context(thread_id_or_message_id) -> List[Turn]`.
  - Update `generate_answer` in `services/openrouter_client.py` to accept conversation history.
  - Update `on_message` and `/ask` in `cogs/rag.py` to detect Discord thread / reply contexts, retrieve recent history (up to 5 turns), and include history in LLM context/prompt.

---

## 5. Document Upload & Parsing Analysis (R2)

### Current Implementation Assessment
- **Status**: **PARTIALLY IMPLEMENTED (PDF + Text + Images via Vision)**.
- **Current Extractor (`services/attachments.py`)**:
  - `_TEXT_EXTENSIONS`: `.txt`, `.md`, `.py`, `.json`, `.csv`, `.log`, `.xml`, `.yaml`, `.yml`, `.html`, `.css`, `.js`, `.ts`. Extracted via UTF-8/Latin-1 text decoding.
  - `.pdf`: Extracted via PyMuPDF (`fitz.open`).
  - `_IMAGE_EXTENSIONS`: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`. Extracted via `_describe_image_with_llm` using Gemini Vision to generate text descriptions.
- **Gaps for Milestone 3 (R2)**:
  - `.docx` (Microsoft Word): Not supported (requires `python-docx`).
  - `.xlsx` (Microsoft Excel): Not supported (requires `openpyxl`).
  - `.pptx` (Microsoft PowerPoint): Not supported (requires `python-pptx`).
  - Structured `.csv` parser: Currently read as raw unparsed text; lacks structured tabular row/column chunking.
  - Code files: Basic extension list present, but extended language files (e.g., `.cpp`, `.java`, `.go`, `.rs`, `.sh`, `.sql`, `.php`) are missing from `_TEXT_EXTENSIONS`.
  - Unified Interface: Needs `parse_document(file_path, file_extension) -> List[DocumentChunk]` as specified in `PROJECT.md`.

---

## 6. VectorStore, Embedding & Search Analysis

### Current Implementation Assessment
- **Status**: **FULLY IMPLEMENTED (State of the Art Qdrant + BM25 + FlashRank)**.
- **Details**:
  - **`services/vectorstore.py`**:
    - Connects to Qdrant at `QDRANT_HOST:QDRANT_PORT` (`qdrant:6333` in Docker).
    - Collection `"discord_rag"` configured with:
      - Dense vector space: `EMBEDDING_DIMENSIONS = 3072` (Cosine distance).
      - Sparse vector space: `SparseVectorParams` using `fastembed.SparseTextEmbedding("Qdrant/bm25")`.
    - Upserts points with payload containing `text`, `metadata`, `original_id`.
    - Querying uses Qdrant Reciprocal Rank Fusion (`models.FusionQuery(fusion=models.Fusion.RRF)`), prefetching `n_results * 4` candidates from both dense and BM25 index.
  - **`services/reranker.py`**:
    - Uses `flashrank.Ranker(model_name="ms-marco-TinyBERT-L-2-v2")`.
    - Re-ranks the fused candidates down to `top_n` (default 5) sorted by score.
  - **`services/openrouter_client.py`**:
    - `get_embedding(texts)` calls OpenRouter embeddings API (`google/gemini-embedding-2-preview`) requesting 3072 dimensions.
    - `generate_answer(question, context, image_paths)` calls OpenRouter chat completions API (`google/gemini-3.1-flash-lite`) with multimodal base64 image support if local image paths are attached.

---

## 7. Testing & Deployment Analysis

### Current Implementation Assessment
- **Testing**:
  - **No automated test suite** exists (0 test files in repository, no `tests/` directory, no `pytest.ini` or test runner).
  - Code syntax validation was confirmed manually via `python -m py_compile`.
- **Deployment**:
  - Dockerized multi-container setup via `docker-compose.yml`:
    - `qdrant`: Official `qdrant/qdrant:latest` image, binding ports `6333` and `6334`, storing data in `./data/qdrant_storage`.
    - `discord-rag-bot-v2`: Built from `Dockerfile`, depends on `qdrant`, mounts `./logs` and `./data`.
  - Slash command sync strategy in `bot.py`:
    - Auto-syncs commands to each guild on bot connection (`on_ready`).
    - Provides owner command `!sync` and script `cleanup_global.py` for global/guild command cleanup to avoid duplicate command entries in Discord UI.

---

## 8. Summary of Identified Gaps & Recommendations

| Area | Current State | Missing / Gap | Recommendation |
|------|---------------|---------------|----------------|
| **Thread & Memory (R1)** | Single-turn Q&A only | No thread detection, no turn buffer, no context memory | Create `services/memory.py`, add turn history to prompt in `generate_answer` |
| **Document Parsers (R2)** | PDF, txt/md/code, image vision | Missing `.docx`, `.xlsx`, `.pptx`, structured `.csv`, additional code extensions | Add dependencies (`python-docx`, `openpyxl`, `python-pptx`), implement `parse_document` |
| **Slash Command Deferral** | All main async slash commands call `defer()` | `/help_format` doesn't defer (minor) | Ensure all slash handlers defer if any network or I/O operation is added |
| **Testing Infrastructure** | 0 test files | No unit or integration test suite | Create `tests/` folder with `pytest` suite for services (`chunker`, `attachments`, `vectorstore`, `memory`) |
| **Doc Alignment** | `README.md` & `.env.example` reference ChromaDB | Documentation out of date with Qdrant code | Update `README.md` and `.env.example` to reflect Qdrant + 3072d + FlashRank |
