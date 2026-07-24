# Handoff Report — Reviewer 2 (Milestone 1 / R1)

## 1. Observation
- Ran syntax verification: `venv\Scripts\python.exe -m py_compile bot.py cogs/rag.py services/conversation_memory.py services/openrouter_client.py` -> Succeeded with exit code 0.
- Ran automated test suite: `venv\Scripts\python.exe -m pytest -v tests/` -> 7 tests passed in 3.16s.
- Inspected `cogs/rag.py`, lines 106–108:
  ```python
  followup_indicators = ["détailler", "expliquer", "plus", "point", "ce", "cette", "lequel", "laquelle", "pourquoi", "comment", "en", "il", "elle"]
  is_short = len(question.split()) < 10
  is_followup = any(kw in question.lower() for kw in followup_indicators)
  ```
  `'en' in 'déploiement'` evaluates to `True`, `'ce' in 'service'` evaluates to `True`, `'il' in 'facile'` evaluates to `True`.
- Inspected `cogs/rag.py`, lines 67–76 (`resolve_context_id`):
  ```python
  if reference and reference.message_id:
      parent_id = str(reference.message_id)
      if memory:
          registered_context = memory.get_context_id_from_message(parent_id)
          if registered_context:
              return registered_context
      return parent_id
  ```
  When `channel` is a `discord.Thread` and `reference.message_id` points to a non-bot message, `registered_context` is `None`, and `parent_id` is returned before checking `isinstance(channel, discord.Thread)`.
- Inspected `services/conversation_memory.py`, lines 82–106 (`cleanup_expired`): Method is defined and tested, but never called in `bot.py` or `cogs/rag.py`.

## 2. Logic Chain
1. **Observation**: Python string `in` operator checks substring inclusion, not whole words.
   - **Reasoning**: `followup_indicators` includes 2-letter strings `"en"`, `"ce"`, and `"il"`. Almost all standard French technical terms (e.g. *déploiement*, *service*, *environnement*, *procédure*) contain these substrings.
   - **Deduction**: `is_followup` evaluates to `True` for virtually every French query, causing `retrieval_query` to concatenate the previous user question regardless of topic change.

2. **Observation**: `resolve_context_id` returns `parent_id` immediately when `reference.message_id` is present and not registered in memory.
   - **Reasoning**: User messages in a Discord thread are not registered in `_message_to_context` (only bot messages are). If a user inside a thread replies to another user's message, `reference` is present, `get_context_id_from_message` returns `None`, and `resolve_context_id` returns `parent_id`.
   - **Deduction**: The code skips `if isinstance(channel, discord.Thread): return str(channel.id)`, fragmenting thread memory and looking up context under an empty message ID context.

## 3. Caveats
- Direct test suite execution (`pytest`) passed 100% because existing tests did not construct string matching edge cases on non-follow-up queries or thread replies targeting non-bot messages.
- No integrity violations (hardcoded test results or facade mocks) were found in the codebase.

## 4. Conclusion
- **Verdict**: **REQUEST_CHANGES**
- Two Major issues must be resolved:
  1. Refine query reformulation in `cogs/rag.py` to use word-boundary matching and remove false-positive 2-letter substrings.
  2. Fix `resolve_context_id` in `cogs/rag.py` so that thread context (`str(channel.id)`) is preserved when replying to non-bot messages inside a Discord thread.

## 5. Verification Method
1. **Syntax Check**:
   `venv\Scripts\python.exe -m py_compile bot.py cogs/rag.py services/conversation_memory.py services/openrouter_client.py`
2. **Automated Unit Tests**:
   `venv\Scripts\python.exe -m pytest -v tests/`
3. **Manual Logic Verification**:
   - Inspect `resolve_context_id` with a mock `discord.Thread` and a `reference` pointing to an unregistered message ID to verify it returns `str(thread.id)`.
   - Inspect query reformulation in `_run_rag_pipeline` with standalone query `"Quels sont les tarifs du service de déploiement ?"` to verify `retrieval_query` does not inappropriately prepend prior turn queries.
