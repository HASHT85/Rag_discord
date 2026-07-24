# Forensic Audit Report — Milestone 1 (R1: Thread Conversation Memory)

**Work Product**: `c:\Projet\Rag_discord`  
**Profile**: General Project / Integrity Forensics  
**Auditor Role**: Forensic Auditor (`critic`, `specialist`, `auditor`)  
**Verdict**: **CLEAN**  

---

## Executive Summary

A comprehensive forensic audit was conducted on Requirement R1 (Thread Conversation Memory & Support) in `c:\Projet\Rag_discord`. The audit evaluated all source implementations (`services/conversation_memory.py`, `services/openrouter_client.py`, `cogs/rag.py`, `bot.py`) and unit/integration test suites (`tests/test_conversation_memory.py`, `tests/test_rag_cog_memory.py`).

No hardcoded responses, facade implementations, mock short-circuits, or pipeline bypasses were detected. All components execute authentic logic, including the 5-turn sliding window memory (`deque(maxlen=5)`), priority-based context ID resolution (`resolve_context_id`), OpenRouter API payload assembly with historical context and multimodal formatting, and regex-based follow-up query expansion with word boundary protection.

---

## Forensic Investigation Results

### Check 1: Hardcoded Test Outputs & Static Dummy Responses
- **Status**: **PASS**
- **Analysis**:
  - Searched all codebase files for fixed output strings, pre-cooked dictionaries, or static return statements.
  - In `cogs/rag.py`, standard fallback returns (`"Aucune source"` on line 51, `"default_context"` on line 85) are structural default returns and not hardcoded test responses.
  - In `services/openrouter_client.py`, all outputs are generated dynamically via API calls to OpenRouter (`_client.chat.completions.create` and `_client.embeddings.create`).
  - Unit tests in `tests/` utilize `unittest.mock` (`AsyncMock`, `patch`) to mock external network boundaries (OpenRouter / Qdrant) appropriately without bypassing internal application logic.

### Check 2: Facade & Dummy Implementation Audit
- **Status**: **PASS**
- **Analysis**:
  - **`services/conversation_memory.py`**: Genuine sliding window implementation storing turns in `deque(maxlen=self.max_turns)`. Manages `_memory`, `_message_to_context`, and `_last_accessed` dicts. Features TTL cleanup for stale histories (`cleanup_expired`).
  - **`services/openrouter_client.py`**: Full production implementation with exponential backoff (`_retry_with_backoff`), error handling for 4xx/5xx HTTP codes, base64 image encoding for multimodal requests, DeepSeek reasoning tag cleanup (`re.sub(r"<think>.*?</think>", "", answer)`), and full `conversation_history` integration.
  - **`cogs/rag.py`**: Genuine RAG cog binding slash command `/ask` and `on_message` listener. Integrates query reformulation, embedding generation, Qdrant hybrid retrieval, FlashRank re-ranking, LLM answer generation, source footer creation, and conversation memory persistence.

### Check 3: Pipeline & Thread Logic Bypass Audit
- **Status**: **PASS**
- **Analysis**:
  - `_run_rag_pipeline` in `cogs/rag.py` (lines 88-195) executes every step sequentially for every query:
    1. Query reformulation check (lines 105-117)
    2. Dense embedding computation (line 120)
    3. Hybrid retrieval in Qdrant (lines 123-127)
    4. FlashRank cross-encoder reranking (line 143)
    5. Context concatenation & attachment extraction (lines 148-183)
    6. LLM answer generation via OpenRouter (lines 186-191)
  - No short-circuit flags or fake bypass branches exist in production code paths.

### Check 4: Genuine Execution of R1 Core Mechanisms
- **Status**: **PASS**
- **Analysis**:
  1. **Sliding Window `deque(maxlen=5)`**: Verified in `services/conversation_memory.py` lines 25-44. Initialized with `max_turns=5` (line 25). Each turn appends `(user_msg, assistant_msg)` pair. Tested in `test_sliding_window_max_5_turns`.
  2. **Context ID Resolution (`resolve_context_id`)**: Verified in `cogs/rag.py` lines 55-86. Strict priority order enforced:
     - Priority 1: Registered bot message reply ID (lines 69-74)
     - Priority 2: Discord thread ID (`isinstance(channel, discord.Thread)` lines 76-77)
     - Priority 3: Unregistered message reply ID (lines 79-80)
     - Priority 4: Channel ID (lines 82-83)
     - Fallback: `"default_context"` (line 85)
     Tested in `test_resolve_context_id_priorities` and `test_resolve_context_id_thread_unregistered_reply`.
  3. **OpenRouter Payload Formatting**: Verified in `services/openrouter_client.py` lines 234-243. Correctly injects `system_prompt`, `conversation_history` turns, and `user_content` array with multimodal support. Tested in `test_generate_answer_formatting_with_history`.
  4. **Follow-Up Query Reformulation**: Verified in `cogs/rag.py` lines 105-117. Uses regex with word boundaries `\b` (`pattern = r'\b(?:' + '|'.join(re.escape(w) for w in followup_indicators) + r')\b'`) matching indicators like `détailler`, `ce point`, `expliquer`, etc. Tested in `test_query_reformulation_false_positives_and_indicators` to ensure no false positives occur on French words containing substrings (e.g. `environnement`).

---

## Empirical Verification Evidence

### 1. Python Syntax Compilation Check
- **Command**:
  `venv\Scripts\python.exe -m py_compile bot.py cogs/rag.py services/conversation_memory.py services/openrouter_client.py`
- **Working Directory**: `c:\Projet\Rag_discord`
- **Result**: `Exit Code: 0` (Clean compilation, zero syntax or import errors)

### 2. Pytest Execution Output
- **Command**:
  `venv\Scripts\python.exe -m pytest -v tests/`
- **Working Directory**: `c:\Projet\Rag_discord`
- **Raw Execution Output**:
```text
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.1.1, pluggy-1.6.0 -- C:\Projet\Rag_discord\venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Projet\Rag_discord
plugins: anyio-4.13.0, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 9 items

tests/test_conversation_memory.py::test_add_turn_and_get_history PASSED  [ 11%]
tests/test_conversation_memory.py::test_sliding_window_max_5_turns PASSED [ 22%]
tests/test_conversation_memory.py::test_reply_chain_message_indexing PASSED [ 33%]
tests/test_conversation_memory.py::test_ttl_cleanup PASSED               [ 44%]
tests/test_conversation_memory.py::test_resolve_context_id_priorities PASSED [ 55%]
tests/test_conversation_memory.py::test_resolve_context_id_thread_unregistered_reply PASSED [ 66%]
tests/test_rag_cog_memory.py::test_generate_answer_formatting_with_history PASSED [ 77%]
tests/test_rag_cog_memory.py::test_simulated_multi_turn_thread_conversation PASSED [ 88%]
tests/test_rag_cog_memory.py::test_query_reformulation_false_positives_and_indicators PASSED [100%]

============================== 9 passed in 4.00s ==============================
```

---

## Adversarial Review & Stress-Test Summary

| Scenario / Assumption | Stress-Test Condition | Observed Behavior | Status |
|-----------------------|-----------------------|-------------------|--------|
| Substring indicator collision | Query "Quel est l'environnement de déploiement ?" containing "en" | Word boundary `\b` regex prevented query expansion | PASS |
| Thread reply precedence | Message in thread replying to a bot message from another context | Priority 1 overrides Priority 2, binding to original context | PASS |
| Unregistered reply in thread | Message in thread replying to an unregistered user message | Priority 2 retained thread ID as context | PASS |
| History overflow | 6 turns added to memory | `deque(maxlen=5)` retained exactly last 5 turns (10 messages) | PASS |
| Inactive conversation decay | Entry untouched for >24 hours | `cleanup_expired(ttl_seconds=86400)` purged entry and message mappings | PASS |

---

## Final Audit Verdict

**VERDICT: CLEAN**

Requirement R1 (Thread Conversation Memory & Support) meets all functional and technical specifications. The implementation is authentic, fully tested, free of facade patterns or artificial shortcuts, and ready for acceptance.
