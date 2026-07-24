# Changes Implemented for Requirement R1 (Reviewer 2 Findings)

## Summary of Modifications

### 1. `cogs/rag.py`
- **Query Reformulation Substring False Positives Fix**:
  - Replaced substring matching (`kw in question.lower()`) with word-boundary regular expression matching:
    `pattern = r'\b(?:' + '|'.join(re.escape(w) for w in followup_indicators) + r')\b'`
    `is_followup = bool(re.search(pattern, question.lower()))`
  - Refined `followup_indicators` list to avoid isolated 2-letter tokens (`"en"`, `"ce"`, `"il"`, `"elle"`) that caused false positives on normal French words like `"environnement"`.
  - Added clean multi-word and distinct follow-up indicators: `"ce point"`, `"le point"`, `"celui-ci"`, `"celle-ci"`, `"ce dernier"`, `"cette dernière"`, `"en savoir plus"`, `"détailler"`, `"expliquer"`, `"préciser"`, `"pourquoi"`, `"comment"`, `"et pour"`, `"qu'en est-il"`, `"plus de détails"`, `"lequel"`, `"laquelle"`, `"lesquels"`, `"lesquelles"`.

- **Discord Thread Context Resolution Priority Fix**:
  - Updated `resolve_context_id`: When inside a `discord.Thread`, thread context (`str(channel.id)`) takes precedence over unregistered message reply references.
  - If a reply `reference` points to a registered bot message with a known `context_id`, that registered `context_id` is returned. If `reference` points to an unregistered message (such as a user message) inside a thread, it now correctly returns `str(channel.id)`.

- **Periodic Context Memory Cleanup Task**:
  - Added `@tasks.loop(hours=1)` (`cleanup_task`) inside `RAGCog` to automatically trigger `self.memory.cleanup_expired(ttl_seconds=86400)` every hour.
  - Added `@cleanup_task.before_loop` to await `self.bot.wait_until_ready()` and `cog_unload` to cancel task loop on cog unload.

### 2. `tests/test_conversation_memory.py`
- Added `test_resolve_context_id_thread_unregistered_reply`:
  - Verifies that when inside a `discord.Thread`, replying to an unregistered user message returns `str(channel.id)`.

### 3. `tests/test_rag_cog_memory.py`
- Added `test_query_reformulation_false_positives_and_indicators`:
  - Verifies that normal French sentences containing tokens/words like `"environnement"` ("en") do NOT trigger follow-up query expansion (`embed_query_normal == question_normal`).
  - Verifies that explicit follow-ups ("Peux-tu détailler le point 2 ?") DO trigger follow-up query expansion (`embed_query_followup` prepends previous query).

---

## Verification Results

### 1. Py_Compile Output
Command:
`venv\Scripts\python.exe -m py_compile bot.py cogs/rag.py services/conversation_memory.py services/openrouter_client.py`

Result: Success (Exit Code 0, 0 syntax/compilation errors).

### 2. Pytest Output
Command:
`venv\Scripts\python.exe -m pytest -v tests/`

Result:
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

============================== 9 passed in 3.44s ==============================
```
