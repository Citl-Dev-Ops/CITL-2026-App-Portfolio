import tempfile
import unittest
from pathlib import Path

from executors import answer_offline
from factbook_ingest import ingest_factbook


SAMPLE_FACTBOOK = """
IRAN

INTRODUCTION
Background: Known as Persia until 1935.

GEOGRAPHY
Location: Middle East.
Land boundaries: total: 5,894 km
border countries (7): Afghanistan 921 km; Armenia 44 km; Azerbaijan 689 km; Iraq 1,599 km; Pakistan 959 km; Turkey 534 km; Turkmenistan 1,148 km
Coastline: 2,440 km
Climate: mostly arid or semiarid
Area: total: 1,648,195 sq km

PEOPLE AND SOCIETY
Population: 86,758,304 (2022 est.)
Ethnic groups: Persian, Azeri, Kurd
Languages: Persian Farsi (official), Azeri
Religions: Muslim 99.6%, other 0.4%
Median age: total: 31.7 years
Literacy: total population: 85.5%
Urbanization: urban population: 76.8% of total population

UNITED ARAB EMIRATES

INTRODUCTION
Background: Trucial states era prior to federation.

GEOGRAPHY
Location: Middle East.
Land boundaries: total: 1,066 km
border countries (2): Oman 609 km; Saudi Arabia 457 km
Coastline: 1,318 km
Climate: desert; cooler in eastern mountains
Area: total: 83,600 sq km

PEOPLE AND SOCIETY
Population: 9,915,000 (2022 est.)
Ethnic groups: Emirati, South Asian, Arab
Languages: Arabic (official), English, Hindi, Urdu
Religions: Muslim, Christian, Hindu
Median age: total: 33.8 years
Literacy: total population: 98.7%
Urbanization: urban population: 87.8% of total population

PERU

INTRODUCTION
Background: Former center of the Inca Empire.

GEOGRAPHY
Location: Western South America.
Land boundaries: total: 7,461 km
border countries (5): Bolivia 1,047 km; Brazil 2,995 km; Chile 171 km; Colombia 1,626 km; Ecuador 1,529 km
Coastline: 2,414 km
Climate: varies from tropical east to arid west
Area: total: 1,285,216 sq km

PEOPLE AND SOCIETY
Population: 33,715,471 (2022 est.)
Ethnic groups: Amerindian, Mestizo, White
Languages: Spanish (official), Quechua, Aymara
Religions: Roman Catholic, Evangelical
Median age: total: 31.3 years
Literacy: total population: 94.5%
Urbanization: urban population: 79.3% of total population
""".strip()


class FactbookReliableQATest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.src = self.base / "factbook.txt"
        self.db = self.base / "factbook.sqlite"
        self.src.write_text(SAMPLE_FACTBOOK, encoding="utf-8")
        ingest_factbook(source_path=self.src, db_path=self.db, source_year=2023, force=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def ask(self, q: str):
        return answer_offline(q, db_path=self.db, source_path=self.src, source_year=2023)

    def test_20_golden_qas(self):
        cases = [
            ("What countries border Iran?", "Iran", "border countries", "Afghanistan"),
            ("What ar e the countries which border Iran?", "Iran", "border countries", "Afghanistan"),
            ("Who are Iran's neighbors?", "Iran", "border countries", "Turkey"),
            ("Border countries of UAE", "United Arab Emirates", "border countries", "Oman"),
            ("What countries border United Arab Emirates?", "United Arab Emirates", "border countries", "Saudi Arabia"),
            ("What is the population of Iran?", "Iran", "population", "86,758,304"),
            ("What languages are spoken in Iran?", "Iran", "languages", "Persian Farsi"),
            ("Main religions in Iran?", "Iran", "religions", "Muslim"),
            ("Ethnic makeup of Iran?", "Iran", "ethnic groups", "Persian"),
            ("Literacy rate in Iran?", "Iran", "literacy", "85.5%"),
            ("Median age in Iran?", "Iran", "median age", "31.7"),
            ("How urbanized is Iran?", "Iran", "urbanization", "76.8%"),
            ("Does Iran have a coastline?", "Iran", "coastline", "2,440 km"),
            ("What is the climate of Iran?", "Iran", "climate", "mostly arid"),
            ("What is the total area of Iran?", "Iran", "area", "1,648,195"),
            ("What languages are spoken in Peru?", "Peru", "languages", "Spanish"),
            ("What are the main religions in Peru?", "Peru", "religions", "Roman Catholic"),
            ("What is the literacy rate in Peru?", "Peru", "literacy", "94.5%"),
            ("Compare population of Iran and Peru.", "Iran", "population", "33,715,471"),
            ("Which has higher literacy: Iran or Peru?", "Iran", "literacy", "94.5%"),
            ("Compare median age of Iran and United Arab Emirates.", "Iran", "median age", "33.8"),
        ]
        for q, expected_country, expected_field, expected_fragment in cases:
            with self.subTest(question=q):
                res = self.ask(q)
                self.assertTrue(res.get("handled"))
                self.assertTrue(res.get("reliable"), msg=f"unexpected non-reliable result for {q}: {res}")
                answer = str(res.get("answer") or "")
                self.assertIn(expected_fragment, answer)
                self.assertIn(expected_country, ", ".join(res.get("detected_entities") or []))
                self.assertEqual(str(res.get("resolved_field") or ""), expected_field)
                self.assertTrue(res.get("country_locked"))
                self.assertGreater(float(res.get("confidence") or 0.0), 0.69)

    def test_negative_control_iran_never_returns_uae_borders(self):
        res = self.ask("What countries border Iran?")
        answer = str(res.get("answer") or "")
        self.assertIn("Afghanistan", answer)
        self.assertNotIn("Oman", answer)
        self.assertNotIn("Saudi Arabia 457", answer)

    def test_country_detected_but_unknown_field_fails_safely(self):
        res = self.ask("What is internet penetration in Iran?")
        self.assertTrue(res.get("handled"))
        self.assertFalse(res.get("reliable"))
        self.assertIn("Cannot answer reliably", str(res.get("answer") or ""))

    def test_citl_factbook_query_works_without_llm_generation(self):
        try:
            import citl_factbook_query as qmod
        except ModuleNotFoundError as e:
            self.skipTest(f"citl_factbook_query import unavailable in test env: {e}")
            return

        prev_factbook = qmod.FACTBOOK_TXT
        try:
            qmod.FACTBOOK_TXT = self.src
            out = qmod.answer_question(
                "What countries border Iran?",
                model="nonexistent-model",
                ollama_host="http://127.0.0.1:1",
            )
            self.assertIn("Detected country/entities: Iran", out)
            self.assertIn("Country locked: true", out)
            self.assertIn("Afghanistan", out)
            self.assertNotIn("Oman 609", out)
        finally:
            qmod.FACTBOOK_TXT = prev_factbook


if __name__ == "__main__":
    unittest.main()
