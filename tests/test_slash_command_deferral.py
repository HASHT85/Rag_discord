"""
Tests de vérification de la défération des commandes slash (< 3s).
Vérifie que 100 % des commandes slash appellent immédiatement `await interaction.response.defer(thinking=True)`.
"""

import ast
import inspect
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import discord

from cogs.admin import AdminCog
from cogs.indexer import IndexerCog
from cogs.rag import RAGCog


EXPECTED_SLASH_COMMANDS = {
    "setup": AdminCog,
    "status": AdminCog,
    "reindex": AdminCog,
    "help_format": AdminCog,
    "note": IndexerCog,
    "doc": IndexerCog,
    "procedure": IndexerCog,
    "tuto": IndexerCog,
    "info": IndexerCog,
    "ask": RAGCog,
}


def get_cog_app_commands(cog_cls):
    """Extrait tous les objets Command d'un Cog."""
    commands = []
    for name, attr in inspect.getmembers(cog_cls):
        if isinstance(attr, discord.app_commands.Command):
            commands.append((attr.name, attr))
    # Aussi vérifier si app_commands est dans les métadonnées de la classe
    if hasattr(cog_cls, "__cog_app_commands__"):
        for cmd in cog_cls.__cog_app_commands__:
            if (cmd.name, cmd) not in commands:
                commands.append((cmd.name, cmd))
    return commands


def test_all_expected_slash_commands_present():
    """Vérifie que les 10 commandes slash prévues sont bien enregistrées dans leurs Cogs respectifs."""
    all_found = {}
    for cog_cls in [AdminCog, IndexerCog, RAGCog]:
        cmds = get_cog_app_commands(cog_cls)
        for name, cmd in cmds:
            all_found[name] = cog_cls

    for expected_name, expected_cog in EXPECTED_SLASH_COMMANDS.items():
        assert expected_name in all_found, f"Commande slash /{expected_name} introuvable dans {expected_cog.__name__}"
        assert all_found[expected_name] == expected_cog, (
            f"Commande slash /{expected_name} associée au mauvais cog : {all_found[expected_name]} au lieu de {expected_cog}"
        )


def test_ast_slash_commands_first_async_defer():
    """
    Analyse l'AST des fonctions de callback de chaque commande slash
    pour s'assurer qu'elles contiennent un appel `defer(thinking=True)`.
    """
    for cog_cls in [AdminCog, IndexerCog, RAGCog]:
        cmds = get_cog_app_commands(cog_cls)
        for name, cmd in cmds:
            callback = cmd.callback
            source = textwrap.dedent(inspect.getsource(callback))
            parsed_ast = ast.parse(source)

            # Recherche d'un nœud Call à interaction.response.defer(thinking=True)
            found_defer = False
            for node in ast.walk(parsed_ast):
                if isinstance(node, ast.Call):
                    # Vérifier si l'appel concerne defer
                    func_node = node.func
                    if isinstance(func_node, ast.Attribute) and func_node.attr == "defer":
                        # Vérifier si argument thinking=True
                        has_thinking = any(
                            kw.arg == "thinking" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                            for kw in node.keywords
                        )
                        if has_thinking:
                            found_defer = True
                            break

            assert found_defer, f"La commande slash /{name} dans {cog_cls.__name__} ne contient pas await interaction.response.defer(thinking=True)"


@pytest.mark.asyncio
async def test_admin_cog_slash_commands_deferral():
    """Vérifie l'exécution des commandes d'administration avec deferral."""
    bot_mock = MagicMock()
    bot_mock.guilds = []
    cog = AdminCog(bot=bot_mock)
    cog.vector_store = MagicMock()

    # /help_format
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await cog.help_format.callback(cog, interaction)
    interaction.response.defer.assert_called_once_with(thinking=True)
    interaction.followup.send.assert_called_once()

    # /status
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    cog.vector_store.get_stats.return_value = {"total_documents": 5}

    with patch("cogs.admin.load_channels_config", return_value={"input_channel_id": 1, "output_channel_id": 2}):
        await cog.status.callback(cog, interaction)
        interaction.response.defer.assert_called_once_with(thinking=True)
        interaction.followup.send.assert_called_once()

    # /setup
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    in_chan = MagicMock(spec=discord.TextChannel)
    in_chan.id = 101
    in_chan.mention = "#input"
    in_chan.send = AsyncMock()
    out_chan = MagicMock(spec=discord.TextChannel)
    out_chan.id = 102
    out_chan.mention = "#output"
    out_chan.send = AsyncMock()

    with patch("cogs.admin.save_channels_config"):
        await cog.setup.callback(cog, interaction, in_chan, out_chan)
        interaction.response.defer.assert_called_once_with(thinking=True)
        interaction.followup.send.assert_called_once()


@pytest.mark.asyncio
async def test_indexer_cog_slash_commands_deferral():
    """Vérifie l'exécution des commandes d'indexation (/note, /doc, /procedure, /tuto, /info) avec deferral."""
    bot_mock = MagicMock()
    cog = IndexerCog(bot=bot_mock)
    cog.vector_store = MagicMock()

    slash_commands = [
        ("note", cog.note_command),
        ("doc", cog.doc_command),
        ("procedure", cog.procedure_command),
        ("tuto", cog.tuto_command),
        ("info", cog.info_command),
    ]

    with patch("cogs.indexer.chunk_text", return_value=["chunk1"]), \
         patch("cogs.indexer.get_embedding", new=AsyncMock(return_value=[[0.1, 0.2]])):

        for name, cmd in slash_commands:
            interaction = MagicMock(spec=discord.Interaction)
            interaction.id = 12345
            interaction.channel_id = 67890
            interaction.channel = MagicMock()
            interaction.channel.name = "general"
            interaction.user = MagicMock()
            interaction.user.__str__ = lambda self: "User#1234"
            interaction.user.display_name = "User"
            interaction.response = MagicMock()
            interaction.response.is_done.return_value = False
            interaction.response.defer = AsyncMock()
            interaction.followup = MagicMock()
            interaction.followup.send = AsyncMock()

            await cmd.callback(cog, interaction, "Titre Test", "Description Test", None)
            interaction.response.defer.assert_called_once_with(thinking=True)
            interaction.followup.send.assert_called_once()


@pytest.mark.asyncio
async def test_rag_cog_ask_command_deferral():
    """Vérifie que la commande /ask de RAGCog exécute defer(thinking=True) en premier."""
    bot_mock = MagicMock()
    bot_mock.wait_until_ready = AsyncMock()
    memory_mock = MagicMock()
    cog = RAGCog(bot=bot_mock, memory=memory_mock)
    cog.vector_store = MagicMock()

    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel_id = 999
    interaction.channel = MagicMock()
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock(return_value=MagicMock(id=888))

    with patch("cogs.rag.load_channels_config", return_value={"output_channel_id": 999}), \
         patch("cogs.rag._run_rag_pipeline", new=AsyncMock(return_value=("Réponse RAG", "Source", None, None))):

        await cog.ask.callback(cog, interaction, "Question test?")
        interaction.response.defer.assert_called_once_with(thinking=True)
        interaction.followup.send.assert_called_once()
