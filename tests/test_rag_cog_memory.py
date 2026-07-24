"""
Integration and unit tests for RAG cog with conversation memory and OpenRouter formatting.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from services.conversation_memory import ConversationMemory
from services.openrouter_client import generate_answer
from cogs.rag import RAGCog, _run_rag_pipeline


@pytest.mark.asyncio
async def test_generate_answer_formatting_with_history():
    """Unit test retrieval of history and formatting in generate_answer."""
    history = [
        {"role": "user", "content": "Quels sont les prérequis pour Docker ?"},
        {"role": "assistant", "content": "Il vous faut un système Linux/Windows/Mac 64-bit."},
    ]

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Le point 2 concerne la mémoire RAM."
    mock_response.choices = [mock_choice]

    with patch("services.openrouter_client._client.chat.completions.create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response

        answer = await generate_answer(
            question="Peux-tu détailler le point 2 ?",
            context="Document de configuration Docker...",
            conversation_history=history,
        )

        assert answer == "Le point 2 concerne la mémoire RAM."
        assert mock_create.called

        # Verify the structure of messages passed to API
        call_kwargs = mock_create.call_args.kwargs
        messages = call_kwargs["messages"]

        # Index 0: System prompt with context
        assert messages[0]["role"] == "system"
        assert "Document de configuration Docker..." in messages[0]["content"]

        # Index 1 & 2: Conversation history
        assert messages[1] == {"role": "user", "content": "Quels sont les prérequis pour Docker ?"}
        assert messages[2] == {"role": "assistant", "content": "Il vous faut un système Linux/Windows/Mac 64-bit."}

        # Index 3: Current user prompt
        assert messages[3]["role"] == "user"
        assert messages[3]["content"][0]["text"] == "Question : Peux-tu détailler le point 2 ?"


@pytest.mark.asyncio
async def test_simulated_multi_turn_thread_conversation():
    """Integration test simulating a multi-turn thread conversation with follow-up queries."""
    memory = ConversationMemory(max_turns=5)
    thread_context_id = "thread_discord_999"

    # Turn 1: User asks initial question
    question_1 = "Quelles sont les étapes d'installation de Docker ?"
    answer_1 = "1. Installer les dépendances. 2. Configurer le dépôt officiel. 3. Démarrer le service."

    mock_vectorstore = MagicMock()
    mock_vectorstore.query.return_value = {
        "ids": ["doc1"],
        "documents": ["Guide d'installation de Docker CE sur Ubuntu..."],
        "metadatas": [{"category": "DevOps", "title": "Guide Docker"}],
    }

    with patch("cogs.rag.get_embedding", new_callable=AsyncMock) as mock_embed, \
         patch("services.reranker.rerank_documents") as mock_rerank, \
         patch("cogs.rag.generate_answer", new_callable=AsyncMock) as mock_gen_answer:

        mock_embed.return_value = [[0.1, 0.2, 0.3]]
        mock_rerank.side_effect = lambda query, documents, top_n: documents
        mock_gen_answer.return_value = answer_1

        ans1, footer1, _, _ = await _run_rag_pipeline(
            vector_store=mock_vectorstore,
            question=question_1,
            conversation_history=memory.get_history(thread_context_id),
        )

        assert ans1 == answer_1
        # Record Turn 1
        memory.add_turn(thread_context_id, question_1, ans1)

        # Check memory state after Turn 1
        history_after_turn1 = memory.get_history(thread_context_id)
        assert len(history_after_turn1) == 2

        # Turn 2: User asks follow-up query "Peux-tu détailler le point 2 ?"
        question_2 = "Peux-tu détailler le point 2 ?"
        answer_2 = "Le point 2 consiste à ajouter la clé GPG et le dépôt APT d'Docker."

        mock_gen_answer.return_value = answer_2

        ans2, footer2, _, _ = await _run_rag_pipeline(
            vector_store=mock_vectorstore,
            question=question_2,
            conversation_history=history_after_turn1,
        )

        assert ans2 == answer_2
        # Record Turn 2
        memory.add_turn(thread_context_id, question_2, ans2)

        # Verify query reformulation for search was executed with combined context
        embed_call_args = mock_embed.call_args[0][0]
        assert question_1 in embed_call_args[0]
        assert question_2 in embed_call_args[0]

        # Verify generate_answer received full conversation history
        gen_answer_call_args = mock_gen_answer.call_args.kwargs
        assert gen_answer_call_args["conversation_history"] == history_after_turn1

        # Final check: Memory now holds 2 turns (4 messages)
        final_history = memory.get_history(thread_context_id)
        assert len(final_history) == 4
        assert final_history[0]["content"] == question_1
        assert final_history[1]["content"] == answer_1
        assert final_history[2]["content"] == question_2
        assert final_history[3]["content"] == answer_2


@pytest.mark.asyncio
async def test_query_reformulation_false_positives_and_indicators():
    """
    Verify that normal French sentences containing 'en', 'ce', 'il' inside words or standalone (e.g. 'Quel est l'environnement de déploiement ?')
    do NOT trigger query expansion, while explicit follow-ups ('Peux-tu détailler le point 2 ?') DO trigger query expansion.
    """
    history = [
        {"role": "user", "content": "Présentation globale du projet RAG Discord."},
        {"role": "assistant", "content": "Le projet RAG Discord permet d'interroger la documentation."},
    ]

    mock_vectorstore = MagicMock()
    mock_vectorstore.query.return_value = {
        "ids": ["doc1"],
        "documents": ["Documentation d'environnement de déploiement..."],
        "metadatas": [{"category": "DevOps", "title": "Deploy"}],
    }

    with patch("cogs.rag.get_embedding", new_callable=AsyncMock) as mock_embed, \
         patch("services.reranker.rerank_documents") as mock_rerank, \
         patch("cogs.rag.generate_answer", new_callable=AsyncMock) as mock_gen_answer:

        mock_embed.return_value = [[0.1, 0.2]]
        mock_rerank.side_effect = lambda query, documents, top_n: documents
        mock_gen_answer.return_value = "Voici les détails d'environnement..."

        # 1. Normal French sentence containing substrings/words like "environnement" ("en")
        question_normal = "Quel est l'environnement de déploiement ?"
        await _run_rag_pipeline(
            vector_store=mock_vectorstore,
            question=question_normal,
            conversation_history=history,
        )
        embed_query_normal = mock_embed.call_args[0][0][0]
        # Must NOT expand query with previous user question
        assert embed_query_normal == question_normal
        assert "Présentation globale" not in embed_query_normal

        # 2. Explicit follow-up sentence containing indicator "détailler" and "le point"
        question_followup = "Peux-tu détailler le point 2 ?"
        await _run_rag_pipeline(
            vector_store=mock_vectorstore,
            question=question_followup,
            conversation_history=history,
        )
        embed_query_followup = mock_embed.call_args[0][0][0]
        # MUST expand query with previous user question
        assert "Présentation globale du projet RAG Discord." in embed_query_followup
        assert "Peux-tu détailler le point 2 ?" in embed_query_followup

