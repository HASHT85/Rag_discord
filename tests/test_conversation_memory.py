"""
Unit tests for ConversationMemory service and context ID resolution.
"""

import time
from unittest.mock import MagicMock
import pytest

from services.conversation_memory import ConversationMemory
from cogs.rag import resolve_context_id


def test_add_turn_and_get_history():
    """Test basic adding of a turn and history retrieval."""
    mem = ConversationMemory(max_turns=5)
    mem.add_turn("thread_1", "Comment installer Python ?", "Tu peux le télécharger sur python.org.")

    history = mem.get_history("thread_1")
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "Comment installer Python ?"}
    assert history[1] == {"role": "assistant", "content": "Tu peux le télécharger sur python.org."}


def test_sliding_window_max_5_turns():
    """Test sliding window mechanism: pushing 6 turns retains only the last 5 turns."""
    mem = ConversationMemory(max_turns=5)
    context_id = "thread_sliding"

    # Push 6 turns
    for i in range(1, 7):
        mem.add_turn(context_id, f"User question {i}", f"Assistant answer {i}")

    history = mem.get_history(context_id)
    # 5 turns = 10 messages (1 user + 1 assistant per turn)
    assert len(history) == 10

    # Turn 1 should be evicted; first message in history should be Turn 2
    assert history[0]["content"] == "User question 2"
    assert history[1]["content"] == "Assistant answer 2"
    # Last message should be Turn 6
    assert history[-2]["content"] == "User question 6"
    assert history[-1]["content"] == "Assistant answer 6"


def test_reply_chain_message_indexing():
    """Test message_id indexing for reply chains."""
    mem = ConversationMemory()

    # Register bot message ID
    mem.register_bot_message("bot_msg_100", "context_thread_42")

    # Retrieve context from message ID
    resolved_ctx = mem.get_context_id_from_message("bot_msg_100")
    assert resolved_ctx == "context_thread_42"

    # Test integer message_id support
    mem.register_bot_message(101, "context_channel_77")
    assert mem.get_context_id_from_message(101) == "context_channel_77"
    assert mem.get_context_id_from_message("101") == "context_channel_77"

    # Unregistered message returns None
    assert mem.get_context_id_from_message("unknown_msg") is None


def test_ttl_cleanup():
    """Test TTL expiration and cleanup of old conversation histories."""
    mem = ConversationMemory()

    # Add active and expired conversations
    mem.add_turn("active_ctx", "Q Active", "A Active")
    mem.add_turn("expired_ctx", "Q Expired", "A Expired")
    mem.register_bot_message("msg_expired_1", "expired_ctx")

    # Manually set timestamp of expired_ctx to 2 days ago (172800 seconds)
    mem._last_accessed["expired_ctx"] = time.time() - 172800

    # Run cleanup with 24h (86400s) TTL
    cleaned_count = mem.cleanup_expired(ttl_seconds=86400)
    assert cleaned_count == 1

    # Check active_ctx remains and expired_ctx is removed
    assert len(mem.get_history("active_ctx")) == 2
    assert len(mem.get_history("expired_ctx")) == 0
    assert mem.get_context_id_from_message("msg_expired_1") is None


def test_resolve_context_id_priorities():
    """Test resolve_context_id logic across reply, thread, and channel scenarios."""
    mem = ConversationMemory()
    mem.register_bot_message("parent_bot_msg_1", "original_context_999")

    # 1. Reply to registered bot message
    ref_registered = MagicMock()
    ref_registered.message_id = "parent_bot_msg_1"
    ctx_id = resolve_context_id(channel=MagicMock(), reference=ref_registered, memory=mem)
    assert ctx_id == "original_context_999"

    # 2. Reply to unregistered message
    ref_unregistered = MagicMock()
    ref_unregistered.message_id = "user_msg_555"
    ctx_id = resolve_context_id(channel=MagicMock(), reference=ref_unregistered, memory=mem)
    assert ctx_id == "user_msg_555"

    # 3. Message inside a Discord Thread (without reply reference)
    thread_mock = MagicMock(spec=["id", "parent_id"])
    thread_mock.id = 888888
    # We patch isinstance check by importing discord.Thread or passing a mock with thread structure
    import discord
    thread_obj = MagicMock(spec=discord.Thread)
    thread_obj.id = 888888
    ctx_id = resolve_context_id(channel=thread_obj, reference=None, memory=mem)
    assert ctx_id == "888888"

    # 4. Message inside a normal Guild text channel
    channel_obj = MagicMock()
    channel_obj.id = 111222
    ctx_id = resolve_context_id(channel=channel_obj, reference=None, memory=mem)
    assert ctx_id == "111222"


def test_resolve_context_id_thread_unregistered_reply():
    """Test resolve_context_id inside a discord.Thread when replying to an unregistered user message."""
    mem = ConversationMemory()
    import discord

    thread_obj = MagicMock(spec=discord.Thread)
    thread_obj.id = 777999

    ref_unregistered = MagicMock()
    ref_unregistered.message_id = "user_msg_unregistered_123"

    # In a thread, reply reference to unregistered user message must return thread ID
    ctx_id = resolve_context_id(channel=thread_obj, reference=ref_unregistered, memory=mem)
    assert ctx_id == "777999"

