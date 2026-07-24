# Handoff Report: Requirement R1 (Conversation Memory & Thread Support)

## 1. Observation

- **`cogs/rag.py`**:
  - Line 53: `async def _run_rag_pipeline(vector_store: VectorStore, question: str, bot: Optional[commands.Bot] = None)`
  - Line 134: `answer = await generate_answer(question=question, context=context, image_paths=image_paths if image_paths else None)`
  - Line 213: `/ask` slash command processes questions statelessly.
  - Line 268: `on_message` listener checks `message.channel.id != output_channel_id` (Line 280), ignoring thread parent relationships (`channel.parent_id`).
- **`services/openrouter_client.py`**:
  - Line 154: `async def generate_answer(question: str, context: str, image_paths: list[str] = None) -> str`
  - Lines 222-227: `messages` list is hardcoded to system prompt + single user content item:
    ```python
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    ```
- **`PROJECT.md` Interface Contract**:
  - Lines 28-30 specify `ConversationMemory` interface:
    - `get_history(channel_or_thread_id: str) -> List[Dict[str, str]]`
    - `add_turn(channel_or_thread_id: str, user_query: str, assistant_response: str)`

---

## 2. Logic Chain

1. **Context Identification**:
   - In Discord, conversation continuation occurs either within a `discord.Thread` (where `channel.id` identifies the thread) or via a message reply referencing a previous bot answer (`message.reference.message_id`).
   - Therefore, a context resolver MUST check if `channel` is a `discord.Thread` first, or if `message.reference` maps to a known bot response message ID.

2. **Memory Buffer & Expiration**:
   - Each turn consists of 1 user query + 1 assistant answer.
   - To maintain a 5-turn sliding window, storing turns in a Python `collections.deque(maxlen=5)` automatically discards the oldest turn when a 6th turn is added.
   - A TTL timestamp tracking (`_last_accessed`) allows `cleanup_expired()` to purge idle memory without unbounded growth.

3. **OpenRouter Integration**:
   - OpenRouter API (OpenAI compatible) supports conversation context by accepting prior turns in the `messages` array between system prompt and current user prompt.
   - Updating `generate_answer` to accept `conversation_history: list[dict]` and iterating through it ensures standard multi-turn LLM reasoning.

4. **Vector Retrieval Query Contextualization**:
   - Short follow-up queries (e.g. *"Peux-tu détailler le point 2 ?"*) lack keywords required for Qdrant vector retrieval.
   - Combining the prior user query with the current query (`f"{last_user_query} | {question}"`) for Qdrant embedding generation ensures relevant document retrieval during follow-ups.

---

## 3. Caveats

- **In-Memory Volatility**: The default design stores memory in process memory. Bot restarts will flush active turn buffers unless optional disk persistence (`json`) is added.
- **Thread Parent Permissions**: If the bot lacks `Read Message History` in threads, fetching parent message references might fail gracefully.
- **Token Limits**: Keeping 5 turns + retrieved context + system prompt is well within Gemini 3.1 Flash's large context window (1M tokens), but max output tokens remain capped at 1500 tokens.

---

## 4. Conclusion

The design for Requirement R1 is fully defined, modular, and directly actionable.
The implementer should execute the following plan:
1. Create `services/conversation_memory.py` implementing `ConversationMemory` with deque sliding window (max 5 turns) and message ID indexing.
2. Update `services/openrouter_client.py` (`generate_answer`) to accept and inject `conversation_history`.
3. Update `cogs/rag.py` to resolve context IDs (thread / reply / channel), contextualize retrieval queries, and record turn history.
4. Implement tests in `tests/test_conversation_memory.py` and `tests/test_rag_cog_memory.py`.

---

## 5. Verification Method

To verify the implementation:

1. **Unit Test Verification**:
   Run pytest:
   ```bash
   pytest tests/test_conversation_memory.py -v
   pytest tests/test_openrouter_client.py -v
   ```
   *Expected result*: All memory store, sliding window (5 turns max), TTL expiration, and API payload tests pass.

2. **Integration & Multi-turn Verification**:
   Run pytest integration suite:
   ```bash
   pytest tests/test_rag_cog_memory.py -v
   ```
   *Expected result*: Simulated multi-turn thread conversation retains turn history and answers follow-up queries correctly.

3. **Files to Inspect**:
   - `services/conversation_memory.py`
   - `services/openrouter_client.py`
   - `cogs/rag.py`
