import hashlib
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import freeze
from frozen import (ROOT, STUDIES, VENDORS, MODELS, MODEL_CONFIG, REPLICATES, STUDY_A_SYSTEM, STUDY_A_INPUTS, RULE_C, RULE_S,
                    SHART, SHAMS, STUDY_B_CELLS, EXACT_TARGETS, PRICES_USD_PER_MTOK, PRICES_SOURCE, build_schedule,
                    build_preflight_schedule, load_schedule, preflight_checks, prereg_canonical, request, schedule_path,
                    canonical, pretty, price_current)

SOURCE_SHA256 = {
    "STUDY_A_SYSTEM": "c4d4ddefdd80c6274e7ce64ad59e539eb0cf35c7270fe0da51255b1e3f3c2b47",
    "RULE_C": "eeedf9deec1d8c46276f0d9cf8d11f64345c33a7d4708d60fb16d4b1c8ef7ca1",
    "RULE_S": "b8bd01d828df7024d5a3797c91142ca1a005fb844452575030fc7fa04b6cba67",
    "SHART": "c5bcdaa6e651d19ad076b2c480be75f00c97da82c96212731f2ab88fc448f825",
    "SHAMS": "516b994b0329c9443d1d5e4696873063c61bfced6483b7ae46e6ba96fede8d15",
    "STUDY_A_INPUTS": "7e9c5924aae248a6287bc4d2cff1c24e09638e75253ec49de2f4bbcdf695cf79",
    "EXACT_TARGETS": "a0c6a1b2dd0df187a3cfc1fdd1c2e22de6c761748c6786880f88172e9b4fa769",
    "STUDY_B_CELLS": "ed0d2f201351912c2e1e7ad08adec2e0ed5a8436178dda39bfb0d00ad2f2c6f0",
    "classifier.py": "64d56b291bcdcd8ec4376d91933b1dd25299c62f335a406d9a989b687510dad8",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


class SourceIdentity(unittest.TestCase):
    """Hashes of the same objects at github.com/theonlypal/opus45-opus46-matched-prereg-final tag v1.0.0."""

    def test_strings(self):
        for name, value in (("STUDY_A_SYSTEM", STUDY_A_SYSTEM), ("RULE_C", RULE_C), ("RULE_S", RULE_S), ("SHART", SHART), ("SHAMS", SHAMS)):
            self.assertEqual(sha(value.encode()), SOURCE_SHA256[name], name)
        self.assertEqual(sha("\n".join(STUDY_A_INPUTS).encode()), SOURCE_SHA256["STUDY_A_INPUTS"])
        self.assertEqual(sha(canonical(EXACT_TARGETS)), SOURCE_SHA256["EXACT_TARGETS"])
        self.assertEqual(sha(canonical(STUDY_B_CELLS)), SOURCE_SHA256["STUDY_B_CELLS"])
        self.assertEqual(sha((ROOT / "classifier.py").read_bytes()), SOURCE_SHA256["classifier.py"])


class GeneratedFiles(unittest.TestCase):
    def test_regenerate(self):
        self.assertEqual((ROOT / "prompts.json").read_bytes(), pretty(freeze.prompts()))
        self.assertEqual((ROOT / "unicode_manifest.json").read_bytes(), pretty(freeze.unicode_manifest()))
        self.assertEqual((ROOT / "protocol.json").read_bytes(), pretty(freeze.protocol()))
        for study in STUDIES:
            for vendor in VENDORS:
                self.assertEqual(schedule_path(study, vendor).read_bytes(), pretty(build_schedule(study, vendor)))
        self.assertEqual((ROOT / "schedules" / "preflight.json").read_bytes(), pretty(build_preflight_schedule()))

    def test_schedule_counts(self):
        per_model = {"A": 8 * REPLICATES["A"], "B": 4 * REPLICATES["B"]}
        total = 0
        for study in STUDIES:
            schedule = load_schedule(study)
            self.assertEqual(len({s["slot_id"] for s in schedule}), len(schedule))
            keys = Counter(tuple(sorted((k, v) for k, v in s.items() if k not in ("slot_id", "replicate", "request_sha256"))) for s in schedule)
            self.assertEqual(set(keys.values()), {REPLICATES[study]})
            self.assertEqual(Counter(s["model"] for s in schedule), {m: per_model[study] for v in VENDORS for m in MODELS[v]})
            total += len(schedule)
        self.assertEqual(json.loads((ROOT / "protocol.json").read_bytes())["requests_total"], total)
        self.assertEqual(total, 4840)
        self.assertEqual(len(load_schedule("preflight")), sum(len(preflight_checks(m)) for v in VENDORS for m in MODELS[v]))
        self.assertEqual(len(load_schedule("preflight")), 28)

    def test_panel(self):
        self.assertEqual([m for v in VENDORS for m in MODELS[v]], list(MODEL_CONFIG))
        self.assertEqual(len(MODEL_CONFIG), 11)
        self.assertNotIn("gemini-3.5-flash", MODEL_CONFIG)
        self.assertEqual(len(STUDY_A_SYSTEM.split()), 20)


class RequestBodies(unittest.TestCase):
    def test_variants(self):
        for slot in load_schedule("A"):
            without = request("A", slot, "omit")[1]
            self.assertNotIn("temperature", without)
            self.assertNotIn("temperature", without.get("generationConfig", {}))
            if MODEL_CONFIG[slot["model"]]["temperature"] == "omit":
                self.assertEqual(list(slot["request_sha256"]), ["omit"])
                with self.assertRaises(AssertionError):
                    request("A", slot, "t0")
                continue
            with_t = request("A", slot, "t0")[1]
            self.assertNotEqual(slot["request_sha256"]["t0"], slot["request_sha256"]["omit"])
            self.assertIn(0, (with_t.get("temperature"), with_t.get("generationConfig", {}).get("temperature")))
        for slot in load_schedule("B"):
            self.assertEqual(list(slot["request_sha256"]), ["omit"])
            with self.assertRaises(AssertionError):
                request("B", slot, "t0")

    def test_study_b_cells(self):
        cells = {"E": (RULE_C, SHART), "F": (RULE_C, SHAMS), "G": (RULE_S, SHART), "H": (RULE_S, SHAMS)}
        for slot in load_schedule("B"):
            b = request("B", slot, "omit")[1]
            if slot["vendor"] == "google":
                pair = (b["systemInstruction"]["parts"][0]["text"], b["contents"][0]["parts"][0]["text"])
                self.assertEqual(b["generationConfig"]["maxOutputTokens"], 16000)
            elif slot["vendor"] == "anthropic":
                pair = (b["system"], b["messages"][0]["content"])
                self.assertEqual(b["max_tokens"], 16000)
            else:
                pair = (b["messages"][0]["content"], b["messages"][1]["content"])
                self.assertEqual(b["max_completion_tokens"], 16000)
            self.assertEqual(pair, cells[slot["cell"]])

    def test_every_model_is_priced(self):
        self.assertEqual(set(PRICES_USD_PER_MTOK), {m for v in VENDORS for m in MODELS[v]})
        self.assertEqual(set(PRICES_SOURCE), set(PRICES_USD_PER_MTOK))
        for model, p in PRICES_USD_PER_MTOK.items():
            self.assertGreaterEqual(float(p["input_ceiling"]), float(p["input"]), model)
        self.assertTrue(price_current("gemini-4-argon", "2026-11-30"))
        self.assertFalse(price_current("gemini-4-argon", "2026-12-01"))
        self.assertFalse(price_current("gemini-3.6-flash", "2027-01-01"))
        self.assertTrue(price_current("kimi-k3", "2030-01-01"))


class Preregistration(unittest.TestCase):
    def test_binding(self):
        data = (ROOT / "PREREG.md").read_bytes()
        protocol = json.loads((ROOT / "protocol.json").read_bytes())
        self.assertEqual(sha(prereg_canonical(data)), protocol["prereg"]["canonical_sha256"])
        self.assertEqual(sha(prereg_canonical(data)), sha(data))
        with_doi = data.replace(b"- Frozen tag: v1.0.0\n", b"- Frozen tag: v1.0.0\nDOI: https://doi.org/10.5281/zenodo.12345678\n")
        self.assertNotEqual(with_doi, data)
        self.assertEqual(prereg_canonical(with_doi), prereg_canonical(data))
        with self.assertRaises(AssertionError):
            prereg_canonical(with_doi.replace(b"DOI: https://doi.org/10.5281/zenodo.12345678\n",
                                              b"DOI: https://doi.org/10.5281/zenodo.12345678\nDOI: https://doi.org/10.5281/zenodo.1\n"))
        for old, new in ((b"at or above 90 percent", b"at or above 80 percent"), (b"zero exact renders", b"few exact renders"),
                         (b"(claude-fable-5-1). Study B", b"(Rayan Pal). Study B"), (b"No mechanism is claimed.", b""),
                         (b"DOI: https://doi.org/", b"doi: https://doi.org/")):
            if old in data:
                self.assertNotEqual(sha(prereg_canonical(data.replace(old, new, 1))), protocol["prereg"]["canonical_sha256"], old)
        self.assertNotEqual(sha(prereg_canonical(data + b"DOI: https://doi.org/10.5281/zenodo.x\n")), sha(data))

    def test_predictions_and_tables(self):
        text = (ROOT / "PREREG.md").read_text()
        self.assertEqual(text.count("Predictions stated before freeze, 2026-10-29T01:24:50Z."), 1)
        self.assertNotIn("<UTC>", text)
        for label in ("PA1 (Rayan Pal).", "PA2 (Rayan Pal).", "PA3 (Rayan Pal).", "PB1 (Rayan Pal).", "PB2 (claude-fable-5-1).",
                      "PB3 (claude-fable-5-1)."):
            self.assertEqual(text.count(label), 1, label)
        self.assertIn(freeze.cost_table(), text)
        self.assertIn(freeze.model_table(), text)
        self.assertIn("UNEXECUTED", text)
        self.assertEqual(json.loads((ROOT / "protocol.json").read_bytes())["preflight"]["status_at_freeze"], "UNEXECUTED")


class Checksums(unittest.TestCase):
    def test_sha256sums_cover_every_file(self):
        excluded = {"SHA256SUMS", "PREREG.md", "FREEZE_COMMIT.txt"}
        files = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()
                       and not {".git", "__pycache__", ".venv"} & set(p.relative_to(ROOT).parts) and p.name not in excluded)
        listed = {}
        for line in (ROOT / "SHA256SUMS").read_text().splitlines():
            h, name = line.split("  ", 1)
            listed[name] = h
        self.assertEqual(sorted(listed), files)
        for name, h in listed.items():
            self.assertEqual(sha((ROOT / name).read_bytes()), h, name)


class Portability(unittest.TestCase):
    def test_no_local_paths_or_keys(self):
        for path in ROOT.rglob("*"):
            if ".git" in path.parts or "__pycache__" in path.parts or not path.is_file() or path.name == "test_frozen.py":
                continue
            text = path.read_bytes().decode("utf-8", "replace")
            self.assertNotIn("/Users/", text, str(path))
            for marker in ("sk-ant-api", "sk-proj-", "AIzaSy"):
                self.assertNotIn(marker, text, str(path))


if __name__ == "__main__":
    unittest.main()
