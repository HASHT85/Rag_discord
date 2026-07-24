"""
Integration tests for Qdrant payload construction and metadata completeness in VectorStore & IndexerCog.
"""

from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from services.vectorstore import VectorStore
from services.chunker import chunk_text
from cogs.indexer import IndexerCog


@pytest.fixture
def mock_vector_store():
    """Provides a VectorStore with mocked QdrantClient and SparseTextEmbedding."""
    with patch("services.vectorstore.QdrantClient") as mock_qdrant_cls, \
         patch("services.vectorstore.SparseTextEmbedding") as mock_bm25_cls:
        
        mock_qdrant = MagicMock()
        mock_qdrant_cls.return_value = mock_qdrant
        mock_qdrant.get_collections.return_value.collections = []

        mock_bm25 = MagicMock()
        mock_bm25_cls.return_value = mock_bm25
        
        # Mock BM25 embedding output
        mock_sparse_res = MagicMock()
        mock_sparse_res.indices.tolist.return_value = [1, 5, 10]
        mock_sparse_res.values.tolist.return_value = [0.5, 0.8, 0.2]
        mock_bm25.embed.return_value = [mock_sparse_res]

        store = VectorStore()
        store.client = mock_qdrant
        yield store, mock_qdrant


def test_qdrant_payload_metadata_fields(mock_vector_store):
    """Verify that VectorStore.add_documents constructs points with complete metadata fields."""
    store, mock_qdrant = mock_vector_store

    texts = ["Sample chunk text content."]
    metadatas = [{
        "message_id": "123456789",
        "channel_id": "987654321",
        "author": "TestUser#0001",
        "category": "Documentation",
        "title": "Architecture Overview",
        "timestamp": "2026-07-24 18:00:00",
        "has_attachment": True,
        "attachment_name": "arch.docx",
        "attachment_url": "https://cdn.discord.com/attachments/123/arch.docx",
        "file_type": "docx",
        "file_ext": ".docx",
        "source": "arch.docx",
        "page_or_sheet_count": 4,
        "chunk_index": 0,
        "total_chunks": 1,
    }]
    ids = ["msg_123456789_chunk_0"]
    embeddings = [[0.1] * 3072]

    store.add_documents(texts, metadatas, ids, embeddings)

    assert mock_qdrant.upsert.called
    call_args = mock_qdrant.upsert.call_args
    assert call_args is not None

    points = call_args.kwargs.get("points") or call_args[1].get("points")
    assert len(points) == 1

    point = points[0]
    payload = point.payload
    assert payload["text"] == "Sample chunk text content."
    assert payload["original_id"] == "msg_123456789_chunk_0"

    metadata = payload["metadata"]
    # Check all mandatory metadata fields
    mandatory_fields = [
        "file_type", "file_ext", "source", "page_or_sheet_count",
        "attachment_name", "attachment_url", "chunk_index", "total_chunks",
        "message_id", "channel_id", "author", "category", "title", "timestamp", "has_attachment",
    ]
    for field in mandatory_fields:
        assert field in metadata, f"Field '{field}' missing from Qdrant metadata payload"

    assert metadata["file_type"] == "docx"
    assert metadata["file_ext"] == ".docx"
    assert metadata["source"] == "arch.docx"
    assert metadata["page_or_sheet_count"] == 4
    assert metadata["chunk_index"] == 0
    assert metadata["total_chunks"] == 1


@pytest.mark.asyncio
async def test_indexer_cog_on_message_with_rich_attachment():
    """Test IndexerCog on_message flow with a DOCX attachment and verify chunk metadata payload."""
    bot = MagicMock()
    indexer = IndexerCog(bot)
    indexer.vector_store = MagicMock()

    # Mock input channel config
    with patch("cogs.indexer.load_channels_config", return_value={"input_channel_id": 1001}), \
         patch("cogs.indexer.extract_attachment_details", new_callable=AsyncMock) as mock_extract, \
         patch("cogs.indexer.get_embedding", new_callable=AsyncMock) as mock_embed:

        mock_extract.return_value = {
            "text": "Extracted DOCX content paragraph 1\nParagraph 2",
            "file_type": "docx",
            "file_ext": ".docx",
            "page_or_sheet_count": 3,
        }
        mock_embed.return_value = [[0.05] * 3072]

        # Mock Discord Message
        message = AsyncMock()
        message.add_reaction = AsyncMock()
        message.reply = AsyncMock()
        message.author.bot = False
        message.channel.id = 1001
        message.channel.name = "input-channel"
        message.id = 555666
        message.content = "[Documentation] Word Specs\nThis document details system specs."
        message.created_at.strftime.return_value = "2026-07-24 18:30:00"

        attachment = MagicMock()
        attachment.filename = "specs.docx"
        attachment.url = "https://cdn.discordapp.com/attachments/1001/specs.docx"
        message.attachments = [attachment]

        await indexer.on_message(message)

        assert indexer.vector_store.add_documents.called
        call_kwargs = indexer.vector_store.add_documents.call_args.kwargs
        metadatas = call_kwargs["metadatas"]
        assert len(metadatas) > 0

        first_meta = metadatas[0]
        assert first_meta["file_type"] == "docx"
        assert first_meta["file_ext"] == ".docx"
        assert first_meta["source"] == "specs.docx"
        assert first_meta["page_or_sheet_count"] == 3
        assert first_meta["attachment_name"] == "specs.docx"
        assert first_meta["attachment_url"] == "https://cdn.discordapp.com/attachments/1001/specs.docx"
        assert first_meta["chunk_index"] == 0
        assert first_meta["total_chunks"] == len(metadatas)


@pytest.mark.asyncio
async def test_text_only_message_metadata_defaults():
    """Test indexing a message without attachments to ensure default metadata values are correct."""
    bot = MagicMock()
    indexer = IndexerCog(bot)
    indexer.vector_store = MagicMock()

    with patch("cogs.indexer.load_channels_config", return_value={"input_channel_id": 1001}), \
         patch("cogs.indexer.get_embedding", new_callable=AsyncMock) as mock_embed:

        mock_embed.return_value = [[0.02] * 3072]

        message = AsyncMock()
        message.add_reaction = AsyncMock()
        message.reply = AsyncMock()
        message.author.bot = False
        message.channel.id = 1001
        message.channel.name = "general"
        message.id = 777888
        message.content = "[Note] Plain text note\nNo attached files here."
        message.attachments = []
        message.created_at.strftime.return_value = "2026-07-24 19:00:00"

        await indexer.on_message(message)

        assert indexer.vector_store.add_documents.called
        call_kwargs = indexer.vector_store.add_documents.call_args.kwargs
        metadatas = call_kwargs["metadatas"]
        meta = metadatas[0]

        assert meta["file_type"] == "text"
        assert meta["file_ext"] == ""
        assert meta["source"] == "discord_message"
        assert meta["page_or_sheet_count"] == 1
        assert meta["attachment_name"] is None
        assert meta["attachment_url"] is None
        assert meta["chunk_index"] == 0
        assert meta["total_chunks"] == 1


def test_chunk_separator_priorities():
    """Test updated separator list in chunker to ensure sheet dividers and code blocks are prioritized."""
    sample_text = (
        "--- Sheet: Sheet1 ---\n"
        "Header 1 | Header 2\n"
        "Value 1 | Value 2\n\n"
        "--- Sheet: Sheet2 ---\n"
        "Header A | Header B\n"
        "Value A | Value B\n\n"
        "# Section Heading\n"
        "Some detailed content under section.\n\n"
        "```python\ndef example():\n    pass\n```"
    )

    chunks = chunk_text(sample_text, chunk_size=100, overlap=0)
    assert len(chunks) > 1
    # Verify dividers are kept together where possible
    assert any("--- Sheet: Sheet1 ---" in c for c in chunks)
    assert any("--- Sheet: Sheet2 ---" in c for c in chunks)
