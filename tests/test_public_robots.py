"""Publisher-style exclusion patterns; no network access is used."""
import unittest

from pokemon_index.public_robots import RobotsPolicy


class PublicRobotsTests(unittest.TestCase):
    def test_wildcards_longest_match_and_allow_tie(self):
        rules = RobotsPolicy("User-agent: *\nDisallow: /b/*?*_nkw\nDisallow: /b/private\n"
                             "Allow: /b/private/approved\nDisallow: /tie\nAllow: /tie\n")
        self.assertFalse(rules.can_fetch("PokemonPublicResearch/1.0", "https://www.ebay.com/b/Pikachu?_nkw=x"))
        self.assertTrue(rules.can_fetch("PokemonPublicResearch/1.0", "https://www.ebay.com/b/Pikachu/1/bn_2"))
        self.assertFalse(rules.can_fetch("PokemonPublicResearch/1.0", "https://www.ebay.com/b/private/secret"))
        self.assertTrue(rules.can_fetch("PokemonPublicResearch/1.0", "https://www.ebay.com/b/private/approved/item"))
        self.assertTrue(rules.can_fetch("PokemonPublicResearch/1.0", "https://www.ebay.com/tie"))

    def test_end_anchor_and_literal_question_mark_are_not_regex(self):
        rules = RobotsPolicy("User-agent: *\nDisallow: /signin/\nAllow: /signin/$\nDisallow: /item?key=1$\n")
        self.assertTrue(rules.can_fetch("research", "https://example.invalid/signin/"))
        self.assertFalse(rules.can_fetch("research", "https://example.invalid/signin/private"))
        self.assertFalse(rules.can_fetch("research", "https://example.invalid/item?key=1"))
        self.assertTrue(rules.can_fetch("research", "https://example.invalid/item?key=12"))

    def test_specific_agent_groups_merge_and_do_not_impersonate_search_bot(self):
        rules = RobotsPolicy("User-agent: *\nDisallow: /sch/\n\nUser-agent: Googlebot\nAllow: /\n\n"
                             "User-agent: PokemonPublicResearch\nDisallow: /private\n\n"
                             "User-agent: PokemonPublicResearch\nDisallow: /other\n")
        self.assertFalse(rules.can_fetch("new-research/1", "https://example.invalid/sch/i.html"))
        self.assertTrue(rules.can_fetch("Googlebot/1", "https://example.invalid/sch/i.html"))
        self.assertFalse(rules.can_fetch("PokemonPublicResearch/1", "https://example.invalid/private"))
        self.assertFalse(rules.can_fetch("PokemonPublicResearch/1", "https://example.invalid/other"))

    def test_encoding_normalization_and_selected_pacing_fail_closed(self):
        rules = RobotsPolicy("User-agent: *\nDisallow: /%69tm/*secret\nCrawl-delay: 2\n\n"
                             "User-agent: Googlebot\nCrawl-delay: 0\n")
        self.assertFalse(rules.can_fetch("research", "https://example.invalid/itm/idsecret"))
        self.assertTrue(rules.requires_pacing("research"))
        self.assertFalse(rules.requires_pacing("Googlebot"))
        self.assertTrue(RobotsPolicy("User-agent: *\nRequest-rate: 1/10\n").requires_pacing("research"))


if __name__ == "__main__":
    unittest.main()
