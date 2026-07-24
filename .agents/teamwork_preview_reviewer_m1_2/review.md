# Review Report: Milestone 1 (R1 — Thread Conversation Memory)

## Review Summary

**Verdict**: **REQUEST_CHANGES**

**Overview**:
The implementation of Requirement R1 introduces a solid baseline for multi-turn conversation memory (`services/conversation_memory.py`), OpenRouter integration (`services/openrouter_client.py`), and RAG cog integration (`cogs/rag.py`). Syntax checks and all 7 automated unit tests pass. However, an adversarial code review revealed two **Major** functional defects in query reformulation heuristics and Discord thread context resolution, alongside two **Minor** operational issues.

---

## Findings

### [Major] Finding 1: Query Reformulation Heuristic Produces Systemic False Positives via Substring Matching
- **Location**: `cogs/rag.py`, lines 106–108
- **What**: The search query reformulation heuristic uses `any(kw in question.lower() for kw in followup_indicators)` with short string tokens including `"en"`, `"ce"`, and `"il"`.
- **Why**: Python's `in` operator performs substring matching. Virtually every French sentence contains substrings like `"en"` (e.g., *déploiement*, *client*, *environnement*), `"ce"` (e.g., *service*, *procédure*, *source*), or `"il"` (e.g., *fichier*, *facile*). Consequently, `is_followup` evaluates to `True` for almost 100% of French user queries regardless of length or topic. This forces `retrieval_query = f"{last_user_query} {question}"` on independent queries, polluting Qdrant vector retrieval with irrelevant historical keywords.
- **Suggestion**: Replace substring matching with word-boundary regex matching (e.g., `re.search(r'\b(?:' + '|'.join(followup_indicators) + r')\b', question.lower())`) or word tokenization, and refine the list of follow-up indicators to remove generic 2-letter substrings.

---

### [Major] Finding 2: Discord Thread Context Resolution Context-Switches on Non-Bot Replies
- **Location**: `cogs/rag.py`, lines 67–76 (`resolve_context_id`)
- **What**: In `resolve_context_id`, when `reference` is present and points to a message not in `memory._message_to_context` (such as a reply to another user's message), the function returns `parent_id` before checking `isinstance(channel, discord.Thread)`.
- **Why**: Inside a Discord Thread, all messages belong to the thread context (`str(thread.id)`). When a user inside a thread replies to another user's message, `resolve_context_id` returns the replied message ID (`"parent_id"`) instead of the thread ID (`"thread_id"`). The bot then queries memory for an empty context, fragmenting thread memory and breaking Requirement R1.
- **Suggestion**: Re-order `resolve_context_id` logic so that if `registered_context` is not found for a reply reference, it checks if `isinstance(channel, discord.Thread)` and returns `str(channel.id)` before falling back to `parent_id`.

---

### [Minor] Finding 3: Inactive Context TTL Cleanup is Unscheduled (Dead Production Code)
- **Location**: `services/conversation_memory.py`, lines 82–106 (`cleanup_expired`)
- **What**: `ConversationMemory.cleanup_expired()` is implemented and unit-tested, but is never invoked anywhere in `cogs/rag.py` or `bot.py`.
- **Why**: Expired conversation histories and message mappings will accumulate indefinitely in RAM over long bot runtimes until process restart.
- **Suggestion**: Add a periodic background task (e.g., `@tasks.loop(hours=1)`) in `cogs/rag.py` or `bot.py` that periodically calls `conversation_memory.cleanup_expired()`.

---

### [Minor] Finding 4: Unit Test Scope Blindspot for Reply References in Threads
- **Location**: `tests/test_conversation_memory.py`, line 104 (`test_resolve_context_id_priorities`)
- **What**: `test_resolve_context_id_priorities` tests Discord thread resolution using `reference=None`.
- **Why**: The test suite does not exercise `resolve_context_id` when a message inside a thread contains a reply reference to a non-bot message, allowing Finding 2 to pass unnoticed in automated tests.
- **Suggestion**: Add an explicit test case in `tests/test_conversation_memory.py` checking `resolve_context_id` behavior when `channel` is a `discord.Thread` and `reference` points to an unregistered user message ID.

---

## Verified Claims

- **Syntax Validity**: `bot.py`, `cogs/rag.py`, `services/conversation_memory.py`, `services/openrouter_client.py` compile cleanly without errors. -> **PASS**
- **Test Suite Execution**: `pytest -v tests/` (7 passed in 3.16s). -> **PASS**
- **Sliding Window Enforcement**: `ConversationMemory(max_turns=5)` correctly retains 5 turns (10 messages) when 6 turns are added, dropping turn 1. -> **PASS**
- **OpenRouter Payload Formatting**: `generate_answer` correctly injects system prompt, historical turn messages, and current user content block into OpenRouter messages array. -> **PASS**
- **Bot Message Reply Tracking**: `register_bot_message` correctly maps bot message ID to context ID for reply resolution when replying to bot responses. -> **PASS**

---

## Coverage Gaps

- **Thread Reply Reference Handling**: Uncovered edge case in `resolve_context_id` where reply inside a thread targets a non-bot message — Risk Level: **HIGH** — Recommendation: **Fix implementation and add unit test**.
- **Query Reformulation Token Boundaries**: Uncovered substring matching behavior in follow-up detection — Risk Level: **HIGH** — Recommendation: **Fix regex/token matching**.

---

## Integrity Check

- **Hardcoded test outputs**: None found.
- **Facade / Dummy implementations**: None found.
- **Shortcut / Bypasses**: None found.
- **Self-certifying work**: Verification performed independently via manual code tracing and execution.
