import unittest
from technical_scoring import factors


class TechnicalScoringTests(unittest.TestCase):
    def spec(self, **extra):
        return {'gpu_tipo':'dedicada', 'gpu_modelo':'rtx 5060', 'ecra_painel':'IPS', 'ecra_tamanho':16, **extra}

    def test_power_is_bounded_and_non_linear(self):
        low = factors(self.spec(tgp_w=60), 85)
        full = factors(self.spec(tgp_w=100), 85)
        boost = factors(self.spec(tgp_w=140), 85)
        self.assertLess(low['tgp_multiplier'], full['tgp_multiplier'])
        self.assertGreaterEqual(low['tgp_multiplier'], .85)
        self.assertEqual(full['tgp_multiplier'], boost['tgp_multiplier'])
        self.assertEqual(factors(self.spec(gpu_tipo='integrada'), 85)['tgp_multiplier'], 1)

    def test_unknown_power_does_not_receive_full_power_credit(self):
        unknown = factors(self.spec(), 85)
        ambiguous = factors(self.spec(tgp_w=115, tgp_evidence_status='ambiguous'), 85)
        family = factors(self.spec(tgp_w=115, tgp_evidence_status='family_only'), 85)
        self.assertEqual(unknown['tgp_multiplier'], ambiguous['tgp_multiplier'])
        self.assertEqual(unknown['tgp_multiplier'], family['tgp_multiplier'])
        self.assertLess(unknown['tgp_multiplier'], 1)

    def test_display_weights_and_utility(self):
        weak = factors(self.spec(ecra_brightness_nits=250, ecra_srgb_percent=65), 85)
        strong = factors(self.spec(ecra_brightness_nits=500, ecra_srgb_percent=100, ecra_painel='OLED'), 85)
        self.assertGreater(strong['display_score'], weak['display_score'])
        self.assertAlmostEqual(sum(strong['display_total_weights'].values()), .10)
        self.assertLessEqual(strong['display_score'], 100)

    def test_hdr_peak_and_invalid_numbers_get_no_bonus(self):
        unknown = factors(self.spec(), 85)
        for value, status in [(1000, 'peak_or_combined'), (float('nan'), None), (float('inf'), None)]:
            row = factors(self.spec(ecra_brightness_nits=value, ecra_brightness_nits_evidence_status=status), 85)
            self.assertEqual(row['brightness'], unknown['brightness'])

    def test_size_rewards_work_area_without_rewarding_unlimited_size(self):
        scores = [factors(self.spec(ecra_tamanho=v), 85)['size'] for v in (14,16,18)]
        self.assertGreater(scores[1], scores[0])
        self.assertGreater(scores[1], scores[2])

    def test_panel_or_dci_does_not_invent_srgb(self):
        spec = self.spec(ecra_painel='OLED', ecra_dci_p3_percent=100)
        self.assertEqual(factors(spec, 85)['gamut'], 100)
        self.assertNotIn('ecra_srgb_percent', spec)
