"""The PHI and REI rules, exactly as contracts/README.md "The rules" says."""
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import rules  # noqa: E402
from agent.rules import Block, Entry, Fact, Harvest, Label, Spray  # noqa: E402

POLICY = {"harvest_start_time": "06:00", "crop_aliases": {"Grapes": "grape", "table grapes": "grape"}}
# Monday Oct 26 2026 to Thursday Oct 29.
MONDAY, THURSDAY = date(2026, 10, 26), date(2026, 10, 29)

FUNGICIDE = Label(1, "Demofung 50 WP", "99999-101", "fungicide", "confirmed", (
    Fact("*", "rei", 12), Fact("grape", "phi", 7 * 24), Fact("strawberry", "phi", 0)))
INSECTICIDE = Label(2, "Demothrin 2EC", "99999-202", "insecticide", "confirmed", (
    Fact("*", "rei", 24), Fact("grape", "phi", 14 * 24), Fact("grape", "rei", 72), Fact("lettuce", "phi", 21 * 24)))

GRAPES = Block("B4", "Block 4", "Grapes")
BERRIES = Block("B1", "Block 1", "strawberry")


def spray(spray_id, block, product, when, reg=None):
    return Spray(spray_id, block.block_id, product, reg, when)


def run(sprays, harvests=(), entries=(), labels=(FUNGICIDE, INSECTICIDE), blocks=(GRAPES, BERRIES), today=MONDAY):
    return rules.evaluate(list(blocks), list(sprays), list(labels), list(harvests), list(entries), POLICY, today)


class PhiTest(unittest.TestCase):
    def test_the_pitch_example(self):
        """Block 4: harvest set for Thursday, but Monday's fungicide needs 7 days."""
        findings = run([spray(1, GRAPES, "Demofung 50 WP", datetime(2026, 10, 26, 8, 0))],
                       [Harvest("H1", "B4", THURSDAY)])
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.kind, "harvest_conflict")
        self.assertEqual((finding.scheduled, finding.earliest, finding.reason), ("2026-10-29", "2026-11-02", "phi"))
        self.assertEqual(finding.interval_hours, 168)

    def test_harvest_on_the_last_day_of_the_phi_is_legal(self):
        self.assertEqual(run([spray(1, GRAPES, "Demofung 50 WP", datetime(2026, 10, 26, 8, 0))],
                             [Harvest("H1", "B4", date(2026, 11, 2))]), [])

    def test_phi_zero_still_waits_for_the_rei(self):
        # Applied 20:00, REI 12 h ends 08:00 next day, after the 06:00 harvest start: the day after that.
        findings = run([spray(1, BERRIES, "Demofung 50 WP", datetime(2026, 10, 26, 20, 0))],
                       [Harvest("H2", "B1", date(2026, 10, 27))])
        self.assertEqual([(f.reason, f.earliest) for f in findings], [("rei", "2026-10-28")])

    def test_rei_ending_at_the_harvest_start_is_legal(self):
        self.assertEqual(run([spray(1, BERRIES, "Demofung 50 WP", datetime(2026, 10, 26, 18, 0))],
                             [Harvest("H2", "B1", date(2026, 10, 27))]), [])

    def test_the_binding_spray_is_the_latest_earliest(self):
        findings = run([spray(1, GRAPES, "Demofung 50 WP", datetime(2026, 10, 20, 8, 0)),
                        spray(2, GRAPES, "Demothrin 2EC", datetime(2026, 10, 22, 8, 0)),
                        spray(3, GRAPES, "Demofung 50 WP", datetime(2026, 10, 25, 8, 0))],
                       [Harvest("H1", "B4", THURSDAY)])
        self.assertEqual([(f.spray_id, f.earliest) for f in findings], [(2, "2026-11-05")])

    def test_sprays_after_the_harvest_dont_count(self):
        self.assertEqual(run([spray(1, GRAPES, "Demofung 50 WP", datetime(2026, 10, 29, 9, 0))],
                             [Harvest("H1", "B4", THURSDAY)]), [])

    def test_past_harvests_are_left_alone(self):
        self.assertEqual(run([spray(1, GRAPES, "Demofung 50 WP", datetime(2026, 10, 20, 8, 0))],
                             [Harvest("H1", "B4", date(2026, 10, 22))], today=MONDAY), [])

    def test_other_blocks_dont_count(self):
        self.assertEqual(run([spray(1, BERRIES, "Demothrin 2EC", datetime(2026, 10, 26, 8, 0))],
                             [Harvest("H1", "B4", THURSDAY)], labels=(INSECTICIDE,)), [
            rules.Finding("crop_not_on_label", "B1", 1, 2, scheduled="2026-10-26T08:00")])


class ReiTest(unittest.TestCase):
    def test_entry_before_the_rei_ends(self):
        findings = run([spray(1, BERRIES, "Demofung 50 WP", datetime(2026, 10, 26, 7, 30))], entries=[
            Entry("E1", "B1", "Crew A", datetime(2026, 10, 26, 13, 0))])
        self.assertEqual([(f.kind, f.earliest, f.interval_hours) for f in findings],
                         [("entry_conflict", "2026-10-26T19:30", 12)])

    def test_entry_when_the_rei_ends_is_legal(self):
        self.assertEqual(run([spray(1, BERRIES, "Demofung 50 WP", datetime(2026, 10, 26, 7, 30))], entries=[
            Entry("E1", "B1", "Crew A", datetime(2026, 10, 26, 19, 30))]), [])

    def test_the_crop_rei_wins_over_the_general_one(self):
        findings = run([spray(1, GRAPES, "Demothrin 2EC", datetime(2026, 10, 26, 7, 0))], entries=[
            Entry("E1", "B4", "Crew B", datetime(2026, 10, 28, 7, 0))])
        self.assertEqual([f.earliest for f in findings], ["2026-10-29T07:00"])


class LabelMatchingTest(unittest.TestCase):
    def test_registration_number_first(self):
        findings = run([spray(1, GRAPES, "the green jug", datetime(2026, 10, 26, 8, 0), reg="99999-101")],
                       [Harvest("H1", "B4", THURSDAY)])
        self.assertEqual([f.kind for f in findings], ["harvest_conflict"])

    def test_name_ignores_case_and_punctuation(self):
        findings = run([spray(1, GRAPES, "DEMOFUNG 50WP", datetime(2026, 10, 26, 8, 0))],
                       [Harvest("H1", "B4", THURSDAY)])
        self.assertEqual([f.kind for f in findings], ["harvest_conflict"])

    def test_unknown_product_is_never_treated_as_safe(self):
        findings = run([spray(1, GRAPES, "Mystery Oil", datetime(2026, 10, 26, 8, 0))], [Harvest("H1", "B4", THURSDAY)])
        self.assertEqual([f.kind for f in findings], ["unknown_product"])

    def test_unconfirmed_label_applies_no_interval(self):
        pending = Label(3, "Demofung 50 WP", "99999-101", "fungicide", "extracted", FUNGICIDE.facts)
        findings = run([spray(1, GRAPES, "Demofung 50 WP", datetime(2026, 10, 26, 8, 0))],
                       [Harvest("H1", "B4", THURSDAY)], labels=(pending,))
        self.assertEqual([(f.kind, f.label_id) for f in findings], [("label_unconfirmed", 3)])

    def test_rejected_labels_never_match(self):
        rejected = Label(3, "Demofung 50 WP", "99999-101", "fungicide", "rejected", FUNGICIDE.facts)
        findings = run([spray(1, GRAPES, "Demofung 50 WP", datetime(2026, 10, 26, 8, 0))],
                       [Harvest("H1", "B4", THURSDAY)], labels=(rejected,))
        self.assertEqual([f.kind for f in findings], ["unknown_product"])

    def test_old_sprays_with_nothing_after_them_are_quiet(self):
        self.assertEqual(run([spray(1, GRAPES, "Mystery Oil", datetime(2026, 8, 1, 8, 0))]), [])

    def test_crop_aliases(self):
        self.assertEqual(rules.crop_key("  Table   Grapes ", {"table grapes": "grape"}), "grape")

    def test_two_readings_keep_the_stricter(self):
        doubled = Label(4, "Demofung 50 WP", None, "fungicide", "confirmed", FUNGICIDE.facts + (
            Fact("grape", "phi", 10 * 24),))
        self.assertEqual(rules.intervals(doubled, "grape", {}), (10, 12))


class KeyTest(unittest.TestCase):
    def test_a_changed_conflict_gets_a_new_key(self):
        one = rules.Finding("harvest_conflict", "B4", 1, 1, harvest_id="H1", scheduled="2026-10-29",
                            earliest="2026-11-02")
        moved = rules.Finding("harvest_conflict", "B4", 1, 1, harvest_id="H1", scheduled="2026-10-30",
                              earliest="2026-11-02")
        self.assertNotEqual(one.key, moved.key)
        self.assertEqual(one.key, rules.Finding(**{**one.__dict__}).key)

    def test_times_are_farm_local(self):
        with self.assertRaises(ValueError):
            rules.parse_datetime("2026-10-26T08:00-07:00")
        self.assertEqual(rules.parse_datetime("2026-10-26 08:00"), datetime(2026, 10, 26, 8, 0))


if __name__ == "__main__":
    unittest.main()
