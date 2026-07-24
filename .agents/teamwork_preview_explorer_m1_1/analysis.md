# Detailed Design & Analysis Report: Conversation Memory & Thread Support (Requirement R1)

## 1. Executive Summary

This report provides the complete architecture and technical design for **Requirement R1: Conversation Memory & Thread Support** in the Discord Multimodal RAG system.

The objective is to allow the Discord RAG bot to maintain context across multi-turn conversations within Discord threads and reply chains. The memory system stores up to the **last 5 turns** (1 turn = 1 user question + 1 assistant response) per thread/channel/reply chain, automatically evicting older turns via a sliding window and purging idle conversations via TTL expiration.

---

## 2. Codebase Investigation & Audit

### 2.1 `cogs/rag.py`
- **Current state**:
  - `_run_rag_pipeline`: Executes dense embedding generation, Qdrant hybrid retrieval, FlashRank re-ranking, and calls `generate_answer(question, context, image_paths)`. It operates statelessly without any conversation context.
  - `ask` slash command: Executes `_run_rag_pipeline` for a given `question` string.
  - `on_message` listener: Listens on the configured `output_channel_id`, verifies message filters, runs `_run_rag_pipeline`, and replies with embeds.
- **Identified Gaps**:
  1. No check or handling for Discord threads (`discord.Thread`) or thread parent IDs (`message.channel.parent_id`).
  2. No lookup of parent message references (`message.reference`) when users reply directly to bot responses.
  3. `_run_rag_pipeline` has no parameter to receive conversation history.
  4. Vector search query does not contextualize short follow-up questions (e.g., *"Peux-tu détailler le point 2 ?"*) using prior turns.

### 2.2 `services/openrouter_client.py`
- **Current state**:
  - `generate_answer(question, context, image_paths)` constructs a system prompt containing retrieved text document context and passes a single user message containing the text question and any multimodal base64 images.
- **Identified Gaps**:
  1. Does not accept `conversation_history`.
  2. The `messages` list submitted to `_client.chat.completions.create` only contains `[system_message, user_message]`. Prior turns are not injected into the OpenRouter payload.

---

## 3. Detailed Technical Design

### 3.1 Service `services/conversation_memory.py`

#### Data Structures
```python
from dataclasses import dataclass, field
from collections import deque
import time
from typing import Optional, List, Dict

@dataclass
class ConversationTurn:
    user_query: str
    assistant_response: str
    timestamp: float = field(default_factory=time.time)

class ConversationMemory:
    def __init__(self, max_turns: int = 5, ttl_seconds: float = 86400):
        self.max_turns = max_turns
        self.ttl_seconds = ttl_seconds
        # Key: context_id (str) -> Deque of ConversationTurn (max 5)
        self._memory: Dict[str, deque[ConversationTurn]] = {}
        # Message ID -> context_id mapping for reply chains outside threads
        self._message_to_context: Dict[str, str] = {}
        # Last activity timestamp per context_id
        self._last_accessed: Dict[str, float] = {}
```

#### Key Capabilities & API
1. **`get_history(context_id: str) -> List[Dict[str, str]]`**:
   - Retrieves history for `context_id`.
   - Returns a list of message dicts formatted for OpenRouter / OpenAI API:
     `[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]`
   - Automatically returns an empty list if expired (`time.time() - last_accessed > ttl_seconds`).

2. **`add_turn(context_id: str, user_query: str, assistant_response: str, message_id: Optional[str] = None)`**:
   - Creates a `ConversationTurn`.
   - Appends to `_memory[context_id]` (which is a `deque(maxlen=self.max_turns)`). When the 6th turn is added, turn 1 is automatically evicted.
   - If `message_id` (the bot reply message ID) is provided, records `_message_to_context[message_id] = context_id`.
   - Updates `_last_accessed[context_id]`.

3. **`get_context_for_message(message_id: str) -> Optional[str]`**:
   - Looks up `_message_to_context.get(message_id)`.

4. **`cleanup_expired() -> int`**:
   - Iterates through `_last_accessed` and purges any `context_id` whose age exceeds `ttl_seconds`. Returns count of purged conversations.

---

### 3.2 Updates to `services/openrouter_client.py`

#### Updated Signature
```python
async def generate_answer(
    question: str,
    context: str,
    image_paths: Optional[list[str]] = None,
    conversation_history: Optional[list[dict[str, str]]] = None,
) -> str:
```

#### Message Payload Construction
```python
# System prompt includes retrieved document context
system_prompt = (
    "Tu es un assistant intelligent intégré dans un serveur Discord. "
    "Tu réponds **toujours en français**.\n\n"
    "Tu disposes du contexte suivant (texte et captures d'écran/images) "
    "indexés sur ce serveur Discord. Utilise **uniquement** ces éléments "
    "pour répondre à la question de l'utilisateur.\n\n"
    "Règles :\n"
    "- Réponds de manière claire, concise et structurée.\n"
    "- Cite tes sources quand c'est possible (catégorie, titre, auteur).\n"
    "- Si le contexte ne contient pas assez d'informations pour répondre, "
    "dis-le honnêtement.\n"
    "- N'invente jamais d'informations qui ne sont pas dans le contexte.\n\n"
    f"--- CONTEXTE TEXTUEL ---\n{context}\n--- FIN DU CONTEXTE TEXTUEL ---"
)

messages = [{"role": "system", "content": system_prompt}]

# Inject up to 5 previous turns (up to 10 messages) if available
if conversation_history:
    for msg in conversation_history:
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

# Append current question turn (with multimodal image content if present)
user_content = [{"type": "text", "text": f"Question : {question}"}]
if image_paths:
    # Add base64 images as before...
    ...

messages.append({"role": "user", "content": user_content})
```

---

### 3.3 Updates to `cogs/rag.py`

#### 1. Integration in `RAGCog`
In `RAGCog.__init__`:
```python
from services.conversation_memory import ConversationMemory

class RAGCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.vector_store = VectorStore()
        self.memory = ConversationMemory(max_turns=5, ttl_seconds=86400)
```

#### 2. Thread & Reply Detection Logic
Helper function in `rag.py`:
```python
def _resolve_context_id(
    memory: ConversationMemory,
    channel: discord.abc.Messageable,
    message: Optional[discord.Message] = None,
) -> str:
    """
    Determines context_id for conversation memory:
    - If channel is a discord.Thread -> thread ID string.
    - If message replies to a previous bot message -> mapped context ID of referenced message.
    - Otherwise -> channel ID string.
    """
    if isinstance(channel, discord.Thread):
        return f"thread_{channel.id}"
    
    if message and message.reference and message.reference.message_id:
        ref_id = str(message.reference.message_id)
        parent_context = memory.get_context_for_message(ref_id)
        if parent_context:
            return parent_context
        return f"reply_{ref_id}"

    return f"channel_{channel.id}"
```

#### 3. Vector Retrieval Query Contextualization
When user asks a follow-up query like *"Peux-tu détailler le point 2 ?"*, dense embedding search needs contextual hints from the immediate prior user question.
In `_run_rag_pipeline`:
```python
retrieval_query = question
if conversation_history:
    # Extract last user query from history to contextualize retrieval
    user_queries = [m["content"] for m in conversation_history if m.get("role") == "user"]
    if user_queries:
        retrieval_query = f"{user_queries[-1]} | {question}"

# Generate embedding and query Qdrant using contextualized retrieval_query
question_embedding = await get_embedding([retrieval_query])
results = vector_store.query(
    query_embedding=question_embedding[0],
    query_text=retrieval_query,
    n_results=TOP_K,
)
```

#### 4. Workflow in Slash `/ask` and `on_message`
- **Output channel restriction check**:
  Allows messages/interactions if `channel_id == output_channel_id` OR `getattr(channel, 'parent_id', None) == output_channel_id`.
- **Pipeline Execution**:
  1. Determine `context_id`.
  2. Fetch `conversation_history = self.memory.get_history(context_id)`.
  3. Execute `_run_rag_pipeline(self.vector_store, question, bot=self.bot, conversation_history=conversation_history)`.
  4. Send Discord embeds and save reply message ID.
  5. Record turn: `self.memory.add_turn(context_id, question, answer, message_id=str(reply_message.id))`.

---

## 4. Test Suite Strategy for Requirement R1

### 4.1 Unit Tests (`tests/test_conversation_memory.py`)
1. **`test_add_and_retrieve_history`**: Verify history addition and formatting (`role`, `content`).
2. **`test_sliding_window_max_5_turns`**: Add 7 turns, verify that only turns 3 to 7 are retained.
3. **`test_context_isolation`**: Verify Thread A and Thread B do not leak memory into each other.
4. **`test_reply_message_mapping`**: Verify parent message ID lookup resolves to the same conversation context.
5. **`test_ttl_expiration`**: Fast-forward time or set small TTL to confirm idle memory auto-purges.

### 4.2 Unit Tests (`tests/test_openrouter_client.py`)
1. **`test_generate_answer_injects_history`**: Mock `_client.chat.completions.create`, assert that payload `messages` contains system prompt + conversation history + current user query.
2. **`test_generate_answer_no_history_backward_compatibility`**: Assert behavior when `conversation_history=None`.

### 4.3 Integration Tests (`tests/test_rag_cog_memory.py`)
1. **`test_thread_conversation_flow`**:
   - Mock Discord Thread.
   - User asks Turn 1: *"Comment configurer Qdrant ?"* -> Bot answers.
   - User asks Turn 2: *"Quels sont les ports par défaut ?"* -> Assert Turn 1 history is passed to pipeline.
2. **`test_follow_up_retrieval_query`**:
   - Verify retrieval query contextualization (combining prior question + follow-up question).

---

## 5. Summary of Recommended Files to Add/Modify

| Action | Path | Description |
|---|---|---|
| **CREATE** | `services/conversation_memory.py` | Implementation of `ConversationMemory` and `ConversationTurn`. |
| **MODIFY** | `services/openrouter_client.py` | Update `generate_answer` signature and message construction. |
| **MODIFY** | `cogs/rag.py` | Add memory instance, thread/reply resolver, and history handling in `_run_rag_pipeline`, `/ask`, and `on_message`. |
| **CREATE** | `tests/test_conversation_memory.py` | Unit tests for memory store and sliding window. |
| **CREATE** | `tests/test_rag_cog_memory.py` | Integration tests for multi-turn thread/reply RAG flow. |
