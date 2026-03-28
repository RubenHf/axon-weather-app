import unittest

from backend.baml_client.types import DailyBriefAnswer
from backend.functions import (
    DISCORD_EMBED_FIELD_VALUE_MAX,
    build_discord_embed,
    format_daily_brief_plain_text,
)


class TestDiscordDailyBriefEmbed(unittest.TestCase):
    def test_embed_maps_fields_in_order(self) -> None:
        brief = DailyBriefAnswer(
            temperatures="Cool morning.",
            precipitation="Dry.",
            wind="Breezy.",
            air_quality="Good.",
            practical_advice="Wear a jacket.",
            overall="Nice day.",
        )
        embed = build_discord_embed(brief)
        self.assertIn("fields", embed)
        names = [f["name"] for f in embed["fields"]]
        self.assertEqual(
            names,
            [
                "Temperatures",
                "Precipitation",
                "Wind",
                "Air Quality",
                "Practical advice",
                "Overall",
            ],
        )
        self.assertNotIn("description", embed)

    def test_embed_empty_sections_uses_fallback_description(self) -> None:
        brief = DailyBriefAnswer(
            temperatures="",
            precipitation="",
            wind="",
            air_quality="",
            practical_advice="",
            overall="",
        )
        embed = build_discord_embed(brief)
        self.assertNotIn("fields", embed)
        self.assertIn("description", embed)
        self.assertIn("could not be generated", embed["description"])

    def test_field_value_truncation(self) -> None:
        long_text = "x" * (DISCORD_EMBED_FIELD_VALUE_MAX + 500)
        brief = DailyBriefAnswer(
            temperatures=long_text,
            precipitation="",
            wind="",
            air_quality="",
            practical_advice="",
            overall="",
        )
        embed = build_discord_embed(brief)
        self.assertIn("fields", embed)
        value = embed["fields"][0]["value"]
        self.assertEqual(len(value), DISCORD_EMBED_FIELD_VALUE_MAX)
        self.assertTrue(value.endswith("…"))

    def test_format_daily_brief_plain_text_skips_empty(self) -> None:
        brief = DailyBriefAnswer(
            temperatures="Only this",
            precipitation="",
            wind="",
            air_quality="",
            practical_advice="",
            overall="",
        )
        text = format_daily_brief_plain_text(brief)
        self.assertEqual(text, "Temperatures\nOnly this")


if __name__ == "__main__":
    unittest.main()
