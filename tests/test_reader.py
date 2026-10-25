"""Reading labels: the reply's shape, and the quote check that proves each fact."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from labels import extract, reader  # noqa: E402
from labels.model import FakeModel, ModelError, Reply  # noqa: E402
from scripts import make_pdf  # noqa: E402

DEMO = ROOT / "demo"


def demo_source(stem: str) -> extract.LabelSource:
    return extract.load(DEMO / "labels" / f"{stem}.txt")


def reply_for(stem: str) -> dict:
    return json.loads((DEMO / "replies" / f"{stem}.json").read_text(encoding="utf-8"))


class DemoRepliesTest(unittest.TestCase):
    """The committed replies are Qwen's own, from scripts/read_label.py on the demo labels."""

    def test_every_demo_fact_is_verified(self):
        for stem in ("demofung-50wp", "demothrin-2ec"):
            with self.subTest(label=stem):
                label = reader.validate(reply_for(stem), demo_source(stem))
                self.assertTrue(all(fact.quote_verified for fact in label.facts), label.facts)

    def test_fungicide_facts(self):
        label = reader.validate(reply_for("demofung-50wp"), demo_source("demofung-50wp"))
        self.assertEqual((label.product_name, label.epa_reg_no, label.product_type),
                         ("DEMOFUNG 50 WP", "99999-101", "fungicide"))
        facts = {(fact.crop, fact.kind): fact.hours for fact in label.facts}
        self.assertEqual(facts[("*", "rei")], 12)
        self.assertEqual(facts[("grapes", "phi")], 168)
        self.assertEqual(facts[("strawberries", "phi")], 0)

    def test_the_model_sees_numbered_lines(self):
        model = FakeModel((DEMO / "replies" / "demofung-50wp.json").read_text(encoding="utf-8"))
        reader.read(demo_source("demofung-50wp"), model)
        text = model.asked[0][0]["text"]
        self.assertIn("p2 L8: - Do not apply within 7 days of harvest.", text)
        self.assertIn("Reply with only one JSON object", text)  # and the prompt carries its own example:
        self.assertIn('"schema": "spraywatch.label/1"', text)


class ParseTest(unittest.TestCase):
    def test_fences_and_chatter_are_tolerated(self):
        data = reader.parse_reply('Here it is:\n```json\n{"schema": "spraywatch.label/1"}\n```')
        self.assertEqual(data, {"schema": "spraywatch.label/1"})

    def test_no_json_is_refused(self):
        for text in ("", "I can't read this label.", "{not json}"):
            with self.subTest(text=text), self.assertRaises(reader.ReplyError):
                reader.parse_reply(text)

    def test_shape_is_enforced(self):
        good = reply_for("demofung-50wp")
        source = demo_source("demofung-50wp")
        bad = [
            {**good, "schema": "other/1"},
            {**good, "product_type": "fertilizer"},
            {**good, "product_name": "<script>alert(1)</script>"},
            {**good, "crops": []},
            {**good, "rei": {**good["rei"], "unit": "weeks"}},
            {**good, "rei": {**good["rei"], "value": -1}},
            {**good, "rei": {**good["rei"], "value": True}},
            {**good, "rei": {**good["rei"], "quote": ""}},
            {**good, "crops": [{"crop": "*", "phi": good["crops"][0]["phi"], "rei": None}]},
        ]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(reader.ReplyError):
                reader.validate(data, source)

    def test_a_crop_given_twice_keeps_both_and_the_rules_take_the_stricter(self):
        from agent import rules

        good = reply_for("demothrin-2ec")
        grapes = good["crops"][1]
        stricter = {**grapes, "condition": "Western states", "phi": {**grapes["phi"], "value": 21, "page": 2,
                                                                    "line": 7, "quote": "Do not apply within 21 days of harvest."}}
        label = reader.validate({**good, "crops": [grapes, stricter, grapes]}, demo_source("demothrin-2ec"))
        phi = [(f.condition, f.value) for f in label.facts if f.kind == "phi"]
        self.assertEqual(phi, [(None, 14), ("Western states", 21)])
        facts = tuple(rules.Fact(f.crop, f.kind, f.hours) for f in label.facts)
        self.assertEqual(rules.intervals(rules.Label(1, "x", None, "insecticide", "confirmed", facts), "grapes", {}),
                         (21, 72))

    def test_an_unreadable_registration_number_is_dropped(self):
        label = reader.validate({**reply_for("demofung-50wp"), "epa_reg_no": "see label"}, demo_source("demofung-50wp"))
        self.assertIsNone(label.epa_reg_no)

    def test_a_cut_off_reply_is_refused(self):
        class CutOff:
            name = "cut"

            def ask(self, content):
                return Reply('{"schema"', 1.0, "length")

        with self.assertRaises(ModelError):
            reader.read(demo_source("demofung-50wp"), CutOff())


class QuoteCheckTest(unittest.TestCase):
    def setUp(self):
        self.source = demo_source("demofung-50wp")

    def check(self, **interval):
        base = {"value": 7, "unit": "days", "page": 2, "line": 8, "quote": "Do not apply within 7 days of harvest"}
        return reader.verify_quote(self.source, {**base, **interval})

    def test_found_where_cited(self):
        self.assertEqual(self.check(), (2, 8, True))

    def test_a_line_or_two_off_is_corrected(self):
        self.assertEqual(self.check(line=10), (2, 8, True))

    def test_found_elsewhere_on_the_page_is_unverified(self):
        self.assertEqual(self.check(line=30), (2, 8, False))

    def test_wrong_number_is_unverified(self):
        self.assertFalse(self.check(value=3)[2])

    def test_words_not_on_the_label_are_unverified(self):
        self.assertFalse(self.check(quote="Do not apply within 7 days of planting")[2])

    def test_wrong_page_is_unverified(self):
        self.assertFalse(self.check(page=1)[2])
        self.assertFalse(self.check(page=9)[2])

    def test_a_quote_that_wraps_lines(self):
        quote = "Do not enter or allow worker entry into treated areas during the restricted entry interval (REI) of 12 hours"
        self.assertEqual(reader.verify_quote(self.source, {"value": 12, "unit": "hours", "page": 1, "line": 17,
                                                           "quote": quote}), (1, 17, True))

    def test_day_of_harvest_is_zero(self):
        self.assertTrue(reader.quote_has_value("May be applied up to the day of harvest", 0, "days"))
        self.assertFalse(reader.quote_has_value("May be applied up to the day of harvest", 1, "days"))

    def test_number_words_and_unit_changes(self):
        self.assertTrue(reader.quote_has_value("Do not apply within seven days of harvest", 7, "days"))
        self.assertTrue(reader.quote_has_value("REI of 48 hours", 2, "days"))
        self.assertTrue(reader.quote_has_value("REI is 3 days", 72, "hours"))
        self.assertFalse(reader.quote_has_value("REI of 48 hours", 4, "days"))

    def test_a_photo_is_never_verified(self):
        photo = extract.LabelSource(Path("label.jpg"), "0" * 64, (), ("image/jpeg", "AAAA"))
        self.assertFalse(reader.verify_quote(photo, {"value": 7, "unit": "days", "page": 1, "line": 0,
                                                     "quote": "Do not apply within 7 days of harvest"})[2])
        content = reader.content_for(photo)
        self.assertEqual(content[1]["type"], "image_url")


@unittest.skipUnless(shutil.which("pdftotext"), "needs poppler-utils")
class PdfTest(unittest.TestCase):
    @unittest.skipUnless((ROOT / "state" / "labels" / "captan-80-df.pdf").is_file(), "run scripts/fetch_labels.sh")
    def test_the_real_captan_label(self):
        """Qwen's saved reply to the real label: every fact verified, every regional variant kept."""
        source = extract.load(ROOT / "state" / "labels" / "captan-80-df.pdf")
        label = reader.validate(reader.parse_reply((DEMO / "replies" / "captan-80-df.json").read_text(encoding="utf-8")),
                                source)
        self.assertEqual((label.product_name, label.epa_reg_no), ("Captan 80 DF", "42750-231"))
        self.assertTrue(all(fact.quote_verified for fact in label.facts))
        grapes = {(f.condition, f.kind): f.hours for f in label.facts if f.crop == "grape"}
        self.assertEqual(grapes, {("U.S. except CA", "phi"): 0, ("U.S. except CA", "rei"): 48,
                                  ("California only", "phi"): 0, ("California only", "rei"): 48})

    def test_a_pdf_reads_like_its_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "demofung-50wp.pdf"
            pdf.write_bytes(make_pdf.pdf_bytes((DEMO / "labels" / "demofung-50wp.txt").read_text(encoding="utf-8")))
            source = extract.load(pdf)
            self.assertEqual(len(source.pages), 2)
            label = reader.validate(reply_for("demofung-50wp"), source)
            self.assertTrue(all(fact.quote_verified for fact in label.facts))

    def test_a_pdf_without_text_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "scan.pdf"
            pdf.write_bytes(make_pdf.pdf_bytes("\n\n"))
            with self.assertRaises(extract.ExtractError):
                extract.load(pdf)


if __name__ == "__main__":
    unittest.main()
