"""Scoring rules on offline runs against mock transports. Responses are synthetic unit-test data, never model observations."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis
import runner
from frozen import EXACT_TARGETS, MODELS, VENDOR_OF
from test_offline_run import KEYS, TODAY, reply, user_text, error

UNAVAILABLE = {"claude-opus-4-5-20251101"}


def text_for(vendor, model, system, user):
    if user == "Hello":
        return "x"
    if user in ("Be silence.", "Be nothing.", "Be the null."):
        return None if vendor in ("anthropic", "google") else ""
    if user in ("Say hello.", "Be a cat.", "Be speech.", "Be something.", "Be a value."):
        return "​" if model == "kimi-k3" and user == "Be a cat." else "Hello."
    matched = ("شَرْط" in system) == (user == "شَرْط")
    if matched:
        return EXACT_TARGETS["T1"] if vendor == "openai" or (vendor == "anthropic" and user == "شَرْط") else "x"
    if vendor == "openai":
        return ""
    if model == "claude-opus-4-6":
        return "Not parsed."
    return "x"


def handler(vendor):
    calls = {"n": 0}

    def handle(request):
        calls["n"] += 1
        body = json.loads(request.content)
        model = request.url.path.split("/")[-1].split(":")[0] if vendor == "google" else body["model"]
        if model in UNAVAILABLE:
            return error(vendor, 404, "not_found_error", "model not found")
        if vendor == "google":
            system = body.get("systemInstruction", {}).get("parts", [{}])[0].get("text", "")
        elif vendor == "anthropic":
            system = body.get("system", "")
        else:
            system = body["messages"][0]["content"] if len(body["messages"]) > 1 else ""
        text = text_for(vendor, model, system, user_text(vendor, body))
        return httpx.Response(200, json=reply(vendor, model, text, calls["n"]))
    return handle


def clients():
    return runner.make_clients(KEYS, {v: httpx.MockTransport(handler(v)) for v in ("openai", "anthropic", "google", "moonshot")})


class Scoring(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(runner, "utc_date", return_value=TODAY), mock.patch.object(runner, "BACKOFF_SECONDS", [0, 0, 0])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_complete_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            c = clients()
            for study in ("preflight", "A", "B"):
                self.assertTrue(runner.execute(study, out, c, frozen=False))
            r = analysis.score(analysis.load(out))
            self.assertEqual(r["PA1"]["sentence_1"]["outcome"], "holds")
            self.assertEqual(r["PA1"]["not_tested"], ["gpt-4-0613"])
            self.assertEqual(r["PA1"]["sentence_1"]["members"]["gpt-5.2-2025-12-11"], {"outcome": "holds", "voids": 90, "valid_completions": 90})
            self.assertEqual(r["PA1"]["sentence_2"]["outcome"], "holds")
            self.assertEqual(r["PA2"]["openai_only_v0_v1"]["outcome"], "holds")
            self.assertEqual(r["PA2"]["anthropic_v2_opus46"]["outcome"], "holds")
            none_other = r["PA2"]["anthropic_v2_none_other"]
            self.assertEqual((none_other["outcome"], none_other["excluded"]), ("fails", ["claude-opus-4-5-20251101"]))
            self.assertEqual(none_other["members"]["claude-fable-5-1"]["V2"], 90)
            self.assertEqual(r["PA2"]["later_anthropic"]["outcome"], "fails")
            self.assertEqual(r["PA2"]["gemini"]["outcome"], "fails")
            self.assertEqual(r["PA2"]["kimi"]["outcome"], "fails")
            pa3 = r["PA3"]["sentence_1"]
            self.assertEqual(pa3["outcome"], "fails")
            self.assertEqual({k: v for k, v in pa3["members"]["kimi-k3"].items() if k in ("visible", "near_void")}, {"visible": 120, "near_void": 30})
            self.assertEqual(pa3["members"]["claude-opus-4-5-20251101"]["outcome"], "not evaluable")
            self.assertEqual(r["PA3"]["sentence_2"]["outcome"], "not evaluable")
            self.assertEqual(r["PB1"]["clause_2"]["outcome"], "not evaluable")
            pooled = r["PB1"]["clause_2"]["pooled_cells_E_H"]
            self.assertEqual(pooled["openai"], {"T1": 400, "valid_completions": 400, "excluded": []})
            self.assertEqual(pooled["anthropic"], {"T1": 100, "valid_completions": 200, "excluded": ["claude-opus-4-5-20251101"]})
            self.assertEqual(r["PB1"]["clause_1"]["T1_by_model_and_cell"]["claude-opus-4-6"]["cells"]["E"], {"T1": 50, "valid_completions": 50})
            self.assertEqual(r["PB2"]["sentence_1"]["outcome"], "not evaluable")
            self.assertEqual(r["PB2"]["sentence_2"]["outcome"], "holds")
            self.assertEqual(r["PB2"]["sentence_3"]["opus46_not_parsed"]["members"]["claude-opus-4-6"],
                             {"outcome": "holds", "containing_not_parsed": 100, "valid_completions": 100})
            self.assertEqual(r["PB3"]["sentence_1"]["outcome"], "not evaluable")
            self.assertEqual(r["PB3"]["sentence_2"], {"outcome": "descriptive", "pa2_gemini_clause": "fails"})
            table = r["tables"]["B"]["models"]["claude-opus-4-5-20251101"]
            self.assertEqual((table["scheduled"], table["op"], table["attempted"], table["valid_completions"]), (200, 200, 0, 0))
            self.assertEqual(r["preflight"]["claude-opus-4-5-20251101"], "OP")

    def test_incomplete_study_is_not_scored(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            c = clients()
            self.assertTrue(runner.execute("preflight", out, c, frozen=False))
            self.assertTrue(runner.execute("A", out, c, frozen=False))
            with mock.patch.object(runner, "MAX_SPEND_USD", 0):
                self.assertFalse(runner.execute("B", out, c, frozen=False))
            r = analysis.score(analysis.load(out))
            self.assertEqual(r["tables"]["B"]["status"], "PAUSED")
            for key in ("sentence_1", "sentence_2"):
                self.assertEqual(r["PB2"][key]["outcome"], "not evaluable")
                self.assertTrue(all(m["reason"] == "study B PAUSED" for m in r["PB2"][key]["members"].values()))
            self.assertEqual(r["PA1"]["sentence_1"]["outcome"], "holds")

    def test_rules_cover_every_prediction(self):
        self.assertLessEqual({"PA1", "PA2", "PA3", "PB1", "PB2", "PB3"}, set(analysis.RULES))
        self.assertEqual(analysis.LATER_ANTHROPIC, ["claude-fable-5-1"])
        self.assertTrue(all(VENDOR_OF[m] == "anthropic" for m in analysis.LATER_ANTHROPIC))
        self.assertEqual(set(MODELS["anthropic"]) - set(analysis.LATER_ANTHROPIC), {"claude-opus-4-5-20251101", "claude-opus-4-6"})


if __name__ == "__main__":
    unittest.main()
