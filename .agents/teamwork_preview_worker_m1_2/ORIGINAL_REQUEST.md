## 2026-07-24T17:40:09Z

You are a Worker subagent assigned to remediate Reviewer 2 findings for Requirement R1 (Thread Conversation Memory).

Your working directory for metadata/reports is: c:\Projet\Rag_discord\.agents\teamwork_preview_worker_m1_2

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Reviewer 2 Findings to Fix:

1. **[Major] Query Reformulation Substring False Positives (`cogs/rag.py`)**:
   - Fix follow-up detection heuristic so it uses word-boundary regex (`re.search(r'\b(?:' + '|'.join(re.escape(w) for w in followup_indicators) + r')\b', question.lower())`) or strict word token matching instead of substring `kw in question.lower()`.
   - Refine follow-up indicators list (e.g., `"ce point"`, `"le point"`, `"celui-ci"`, `"celle-ci"`, `"ce dernier"`, `"en savoir plus"`, `"détailler"`, `"préciser"`, `"pourquoi"`, `"comment"`, `"et pour"`, `"qu'en est-il"`, `"plus de détails"`, etc.) avoiding isolated 2-letter tokens like `"en"`, `"ce"`, `"il"`.

2. **[Major] Discord Thread Context Resolution Priority (`cogs/rag.py` / `services/conversation_memory.py`)**:
   - Update `resolve_context_id`: When inside a `discord.Thread`, all messages within the thread belong to the thread context (`str(channel.id)`), UNLESS the reply reference is explicitly a registered bot message with a known context ID. If `reference` points to an unregistered message (like a user message), inside a thread it MUST return `str(channel.id)`.

3. **[Minor] Periodic Context Memory Cleanup (`cogs/rag.py` or `bot.py`)**:
   - Add a Discord tasks loop `@tasks.loop(hours=1)` in `cogs/rag.py` (or call `conversation_memory.cleanup_expired()`) so idle memory entries are cleaned up automatically.

4. **[Minor] Expanded Unit Test Suite (`tests/test_conversation_memory.py` & `tests/test_rag_cog_memory.py`)**:
   - Add unit test for `resolve_context_id` when inside a `discord.Thread` with a reply reference to an unregistered user message.
   - Add unit test verifying that normal French sentences containing "en", "ce", "il" (e.g., "Quel est l'environnement de déploiement ?") do NOT trigger follow-up query expansion, while explicit follow-ups ("Peux-tu détailler le point 2 ?") DO trigger follow-up query expansion.

Execution Steps:
- Modify `cogs/rag.py`, `services/conversation_memory.py`, `tests/test_conversation_memory.py`, `tests/test_rag_cog_memory.py`.
- Run compilation: `venv\Scripts\python.exe -m py_compile bot.py cogs/rag.py services/conversation_memory.py services/openrouter_client.py`
- Run test suite: `venv\Scripts\python.exe -m pytest -v tests/`
- Report results and test outputs in `c:\Projet\Rag_discord\.agents\teamwork_preview_worker_m1_2\changes.md` and `handoff.md`.
