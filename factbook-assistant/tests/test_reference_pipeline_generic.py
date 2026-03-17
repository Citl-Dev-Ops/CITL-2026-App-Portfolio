import json
import tempfile
import unittest
from pathlib import Path

from citl_factbook.reference_ingest import ingest_corpus
from citl_factbook.reference_query import answer_reference_question, render_reference_result


SAMPLE_TECH_REF = """
ROUTER ALPHA

OVERVIEW
Summary: Edge routing appliance for branch sites.

SPECIFICATIONS
Ports: 48
Power Draw: 72 W
Protocols: OSPF, BGP

TROUBLESHOOTING
Reset: Hold reset for 10 seconds.

SWITCH BETA

OVERVIEW
Summary: Access switch for campus floors.

SPECIFICATIONS
Ports: 24
Power Draw: 34 W
Protocols: STP, LLDP

TROUBLESHOOTING
Reset: Cycle power and reload startup-config.
""".strip()


TECH_CONFIG = {
    "mode": "reference",
    "entity_heading_regex": r"(?m)^\s*([A-Z][A-Z ]{3,})\s*$",
    "entity_required_markers": [],
    "entity_probe_chars": 1200,
    "section_heading_regex": r"(?m)^\s*(OVERVIEW|SPECIFICATIONS|TROUBLESHOOTING)\s*$",
    "known_sections": ["OVERVIEW", "SPECIFICATIONS", "TROUBLESHOOTING"],
    "field_line_regex": r"^([A-Za-z][A-Za-z0-9 /()'%,.-]{1,72}):\s*(.*)$",
    "canonical_fields": {
        "port count": {
            "section": "SPECIFICATIONS",
            "labels": ["Ports"],
            "aliases": ["port count", "ports", "how many ports"],
        },
        "power draw": {
            "section": "SPECIFICATIONS",
            "labels": ["Power Draw"],
            "aliases": ["power draw", "power", "wattage"],
        },
    },
}


class GenericReferencePipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.src = self.base / "tech_reference.txt"
        self.cfg = self.base / "tech_config.json"
        self.db = self.base / "reference.sqlite"
        self.src.write_text(SAMPLE_TECH_REF, encoding="utf-8")
        self.cfg.write_text(json.dumps(TECH_CONFIG), encoding="utf-8")

        ingest_corpus(
            source_path=self.src,
            corpus_name="network_hw",
            db_path=self.db,
            config_path=self.cfg,
            source_year=2026,
            force=True,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def ask(self, q: str):
        return answer_reference_question(
            question=q,
            corpus_name="network_hw",
            db_path=self.db,
            source_path=self.src,
            config_path=self.cfg,
            source_year=2026,
            auto_ingest=True,
        )

    def test_structured_lookup(self):
        res = self.ask("What is the port count of Router Alpha?")
        self.assertTrue(res.get("handled"))
        self.assertTrue(res.get("reliable"))
        self.assertTrue(res.get("country_locked"))
        self.assertIn("48", str(res.get("answer") or ""))
        self.assertEqual("port count", str(res.get("resolved_field") or ""))
        txt = render_reference_result(res)
        self.assertIn("Entity locked: true", txt)

    def test_comparison(self):
        res = self.ask("Compare power draw of Router Alpha and Switch Beta.")
        self.assertTrue(res.get("handled"))
        self.assertTrue(res.get("reliable"))
        answer = str(res.get("answer") or "")
        self.assertIn("72 W", answer)
        self.assertIn("34 W", answer)

    def test_negative_entity_lock(self):
        res = self.ask("How many ports does Router Alpha have?")
        self.assertTrue(res.get("reliable"))
        answer = str(res.get("answer") or "")
        self.assertIn("48", answer)
        self.assertNotIn("24", answer)

    def test_unknown_field_fails_safely(self):
        res = self.ask("What is the rack unit height of Router Alpha?")
        self.assertTrue(res.get("handled"))
        self.assertFalse(res.get("reliable"))
        self.assertIn("Cannot answer reliably", str(res.get("answer") or ""))


if __name__ == "__main__":
    unittest.main()
