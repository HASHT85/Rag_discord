# Project: Discord Multimodal RAG System

## Architecture & Code Layout
- `bot.py`: Main Discord bot entrypoint, cog loader, event handlers (`on_ready`, `on_message`).
- `config.py`: Configuration variables, Qdrant parameters (3072d Dense + BM25 Sparse), OpenRouter/Gemini settings.
- `cogs/`: Discord bot cogs:
  - `rag.py`: `/ask` slash command and channel/thread `on_message` listener with multi-turn conversation memory.
  - `indexer.py`: `/doc`, `/note`, `/procedure`, `/tuto`, `/info` document indexing slash commands.
  - `admin.py`: `/setup`, `/status`, `/reindex`, `/help_format`.
- `services/`: Core logic services:
  - `attachments.py`: File download and rich document format extractors (.docx, .xlsx, .pptx, .csv, .md, .py, .js, .json, .html, .css, .pdf, images).
  - `chunker.py`: Document text chunking service with structural separator preservation.
  - `vectorstore.py`: Qdrant hybrid vector database client (Dense 3072d + BM25 Sparse with RRF) and metadata payload construction.
  - `reranker.py`: FlashRank cross-encoder reranker (`ms-marco-TinyBERT-L-2-v2`).
  - `openrouter_client.py`: OpenRouter Gemini 3.1 LLM and Vision API client.
  - `conversation_memory.py`: Thread context & 5-turn sliding window conversation memory buffer.

## Milestones Table
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Architecture Exploration | Codebase investigation & baseline check | None | DONE |
| M2 | R1: Conversation Memory & Thread Support | Multi-turn memory buffer (last 5 turns) for Discord threads & replies | M1 | DONE |
| M3 | R2: Extended Document Parsers & Qdrant Indexing | Parsers for .docx, .xlsx, .pptx, .csv, .md, code files (.py, .js, .json, .html, .css) & indexing | M1 | DONE |
| M4 | Verification, Git & VPS Deployment | Slash command deferral audit (<3s), E2E test suite, git commit/push, VPS deploy | M2, M3 | IN_PROGRESS |

## Interface Contracts
### Conversation Memory (R1)
- `ConversationMemory`:
  - `get_history(context_id: str) -> List[Dict[str, str]]`: Returns up to last 5 turn message pairs (`{"role": "user"|"assistant", "content": str}`) for a thread or reply context.
  - `add_turn(context_id: str, user_query: str, assistant_response: str)`: Appends turn and enforces max 5 turns window (`deque(maxlen=5)`).
  - `register_bot_message(message_id: str, context_id: str)`: Maps bot response message ID to context ID for reply chains.

### Extended Document Extractors (R2)
- `services/attachments.py`:
  - `extract_attachment_content(attachment, bot) -> Tuple[Optional[str], Optional[str], Dict]`: Extracts text content, format, and metadata from `.docx`, `.xlsx`, `.pptx`, `.csv`, `.md`, `.pdf`, `.py`, `.js`, `.json`, `.html`, `.css`.

### Slash Command Deferral
- All slash commands MUST execute `await interaction.response.defer(thinking=True)` within 3 seconds of invocation before any network or disk I/O.
