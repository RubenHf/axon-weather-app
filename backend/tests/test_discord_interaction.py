import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.functions import (
    _discord_interaction_content_payload,
    patch_discord_interaction_original_message,
)
from backend.settings import get_discord_slash_reply_ephemeral


class TestDiscordInteractionPatch(unittest.IsolatedAsyncioTestCase):
    async def test_patch_original_uses_expected_url_and_json(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        inner_client = MagicMock()
        inner_client.patch = AsyncMock(return_value=mock_response)
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(return_value=inner_client)
        context_manager.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.functions.httpx.AsyncClient", return_value=context_manager):
            await patch_discord_interaction_original_message(
                application_id="123456789",
                interaction_token="interaction_token",
                content="Forecast text",
            )

        inner_client.patch.assert_called_once()
        call_args = inner_client.patch.call_args
        self.assertEqual(
            call_args.args[0],
            "https://discord.com/api/v10/webhooks/123456789/interaction_token/messages/@original",
        )
        self.assertEqual(call_args.kwargs["json"], {"content": "Forecast text"})

    async def test_patch_original_includes_ephemeral_flag(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        inner_client = MagicMock()
        inner_client.patch = AsyncMock(return_value=mock_response)
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(return_value=inner_client)
        context_manager.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.functions.httpx.AsyncClient", return_value=context_manager):
            await patch_discord_interaction_original_message(
                application_id="1",
                interaction_token="tok",
                content="Hi",
                ephemeral=True,
            )

        self.assertEqual(
            inner_client.patch.call_args.kwargs["json"],
            {"content": "Hi", "flags": 64},
        )

    def test_content_payload_truncates_over_2000_chars(self) -> None:
        long = "x" * 2500
        body = _discord_interaction_content_payload(long)
        self.assertEqual(len(body["content"]), 2000)
        self.assertTrue(body["content"].endswith("..."))

    def test_slash_reply_ephemeral_builtin_defaults(self) -> None:
        self.assertTrue(get_discord_slash_reply_ephemeral("2_hours"))
        self.assertTrue(get_discord_slash_reply_ephemeral("4_hours"))
        self.assertFalse(get_discord_slash_reply_ephemeral("weather"))

    def test_slash_reply_ephemeral_unknown_command_defaults_private(self) -> None:
        self.assertTrue(get_discord_slash_reply_ephemeral("unknown_command"))


if __name__ == "__main__":
    unittest.main()
