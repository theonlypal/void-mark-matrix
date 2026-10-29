"""Offline end-to-end runs against mock transports. Responses are synthetic unit-test data, never model observations."""
import json
import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import frozen
import runner
import verify
from frozen import VENDORS, MODELS, MODEL_CONFIG, load_schedule

KEYS = {v: f"synthetic-{v}-key" for v in VENDORS}
REJECTS_TEMPERATURE = {"gpt-5.5-2026-04-23", "claude-fable-5-1", "gemini-4-argon", "kimi-k3"}
UNAVAILABLE = {"claude-opus-4-5-20251101"}
TODAY = "2026-10-29"


def counter():
    lock, state = threading.Lock(), {"n": 0}

    def next_call():
        with lock:
            state["n"] += 1
            return state["n"]
    return next_call


def user_text(vendor, body):
    if vendor == "google":
        return body["contents"][0]["parts"][0]["text"]
    return body["messages"][-1]["content"]


def has_temperature(vendor, body):
    return "temperature" in (body["generationConfig"] if vendor == "google" else body)


def reply(vendor, model, text, call):
    if vendor == "anthropic":
        return {"id": f"msg_synthetic{call}", "type": "message", "role": "assistant", "model": model,
                "content": [] if text is None else [{"type": "text", "text": text}], "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}
    if vendor == "google":
        return {"candidates": [{"content": {"role": "model", "parts": [] if text is None else [{"text": text}]}, "finishReason": "STOP"}],
                "modelVersion": model, "responseId": f"resp{call}", "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 1}}
    return {"id": f"chatcmpl{call}", "model": model, "usage": {"prompt_tokens": 10, "completion_tokens": 1},
            "choices": [{"message": {"role": "assistant", "content": text if text is not None else ""}, "finish_reason": "stop"}]}


def error(vendor, status, kind, message):
    if vendor == "google":
        return httpx.Response(status, json={"error": {"code": status, "message": message, "status": kind}})
    if vendor == "anthropic":
        return httpx.Response(status, json={"type": "error", "error": {"type": kind, "message": message}})
    return httpx.Response(status, json={"error": {"type": kind, "message": message}})


def responder(vendor, delay=0, returned=None, calls=None):
    next_call = counter()

    def handle(request):
        call = next_call()
        if calls is not None:
            calls.append(request)
        time.sleep(delay)
        assert request.headers.get("authorization", request.headers.get("x-api-key", request.headers.get("x-goog-api-key"))).endswith(KEYS[vendor])
        body = json.loads(request.content)
        model = request.url.path.split("/")[-1].split(":")[0] if vendor == "google" else body["model"]
        if model in UNAVAILABLE:
            return error(vendor, 404, "not_found_error", "model not found")
        if model in REJECTS_TEMPERATURE and has_temperature(vendor, body):
            return error(vendor, 400, "invalid_request_error", "temperature is not supported for this model")
        text = None if "silence" in user_text(vendor, body) else "x"
        return httpx.Response(200, headers={"request-id": f"req{call}"}, json=reply(vendor, returned or model, text, call))
    return handle


def clients(handlers=None):
    handlers = handlers or {}
    return runner.make_clients(KEYS, {v: httpx.MockTransport(handlers.get(v) or responder(v)) for v in VENDORS})


def completion(out, study):
    return json.loads((out / verify.folder_name(study) / "completion.json").read_bytes())


def events(out, study):
    return [json.loads(l) for l in (out / verify.folder_name(study) / "events.jsonl").read_bytes().splitlines()]


class Offline(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(runner, "utc_date", return_value=TODAY), mock.patch.object(runner, "BACKOFF_SECONDS", [0, 0, 0])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def preflight(self, out, c=None):
        self.assertTrue(runner.execute("preflight", out, c or clients(), frozen=False))
        return json.loads((out / "preflight" / "verdict.json").read_bytes())

    def test_full_run_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            c = clients()
            verdict = self.preflight(out, c)
            for model, v in verdict["models"].items():
                probe = MODEL_CONFIG[model]["temperature"] == "probe"
                expected = ("OP", None) if model in UNAVAILABLE else ("PASS", "t0" if probe and model not in REJECTS_TEMPERATURE else "omit")
                self.assertEqual((v["status"], v["study_a_variant"]), expected, model)
                self.assertEqual(sorted(v["checks"]), ["A-omit", "A-t0", "B"] if probe else ["A-omit", "B"])
            self.assertTrue(runner.execute("A", out, c, frozen=False))
            ledger, counts = verify.verify_study(out, "A", verdict)
            self.assertEqual(ledger.status, "COMPLETE")
            for (vendor, model, prompt), cl in counts.items():
                expected = {"OP": 30} if model in UNAVAILABLE else {("V2" if vendor in ("anthropic", "google") else "V0") if "silence" in prompt else "R": 30}
                self.assertEqual(dict(cl), expected, (vendor, model, prompt))
            variants = {e["data"]["variant"] for e in events(out, "A") if e["event"] == "attempt_started"
                        and e["data"]["slot_id"].startswith("A-moonshot")}
            self.assertEqual(variants, {"omit"})
            self.assertTrue(runner.execute("B", out, c, frozen=False))
            ledger, counts = verify.verify_study(out, "B", verdict)
            self.assertEqual(ledger.status, "COMPLETE")
            op = [r for r in ledger.definitive.values() if r["class"] == "OP"]
            self.assertEqual(len(op), 200)
            self.assertTrue(all(not (out / "studyB" / "attempts" / r["slot_id"]).exists() for r in op))
            for p in out.rglob("*"):
                if p.is_file():
                    data = p.read_bytes()
                    self.assertFalse(any(k.encode() in data for k in KEYS.values()), str(p))
            with self.assertRaises(AssertionError):
                runner.execute("B", out, c, frozen=False)
            with mock.patch.object(sys, "argv", ["verify.py", "--output", str(out)]):
                self.assertEqual(verify.main(), 0)

    def test_tampering_fails_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            c = clients()
            verdict = self.preflight(out, c)
            self.assertTrue(runner.execute("B", out, c, frozen=False))
            target = next((out / "studyB" / "attempts").iterdir()) / "attempt-01"
            for name, edit in (("response.bin", lambda b: b.replace(b'"x"', b'"y"')),
                               ("classification.json", lambda b: b.replace(b'"class":"', b'"class":"X')),
                               ("classifier_input.bin", lambda b: b + b" ")):
                original = (target / name).read_bytes()
                (target / name).write_bytes(edit(original))
                with self.assertRaises(AssertionError):
                    verify.verify_study(out, "B", verdict)
                (target / name).write_bytes(original)
            verify.verify_study(out, "B", verdict)
            events_path = out / "studyB" / "events.jsonl"
            original = events_path.read_bytes()
            tampered = original.replace(b'"class":"OT"', b'"class":"V0"', 1)
            self.assertNotEqual(tampered, original)
            events_path.write_bytes(tampered)
            with self.assertRaises(AssertionError):
                verify.verify_study(out, "B", verdict)

    def test_continuation_and_safety_are_final_without_follow_up(self):
        calls = []
        base = responder("google", calls=calls)

        def handle(request):
            response = base(request)
            body, text = json.loads(response.content), user_text("google", json.loads(request.content))
            if text in ("Be nothing.", "Be a cat."):
                body["candidates"][0]["finishReason"] = "CONTINUATION" if text == "Be nothing." else "SAFETY"
                body["candidates"][0]["content"] = {"role": "model", "parts": [{"text": ""}]}
                body["candidates"][0]["continuationToken"] = "synthetic"
            return httpx.Response(200, json=body)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            c = clients({"google": handle})
            verdict = self.preflight(out, c)
            self.assertTrue(runner.execute("A", out, c, frozen=False))
            ledger, counts = verify.verify_study(out, "A", verdict)
            for (vendor, model, prompt), cl in counts.items():
                if vendor == "google":
                    expected = {"Be nothing.": "CN", "Be a cat.": "SB", "Be silence.": "V2"}.get(prompt, "R")
                    self.assertEqual(dict(cl), {expected: 30}, (model, prompt))
            google_slots = sum(1 for s in load_schedule("A") if s["vendor"] == "google")
            google_preflight = sum(1 for s in load_schedule("preflight") if s["vendor"] == "google")
            self.assertEqual(len(calls), google_slots + google_preflight)
            self.assertFalse(any(b"continuationToken" in r.content for r in calls))

    def test_price_expiry_pauses(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            c = clients()
            self.preflight(out, c)
            dates = iter([TODAY])
            with mock.patch.object(runner, "utc_date", side_effect=lambda: next(dates, "2026-12-01")):
                self.assertFalse(runner.execute("B", out, c, frozen=False))
            self.assertEqual((completion(out, "B")["status"], completion(out, "B")["reason"]), ("PAUSED", "price expired"))
            with mock.patch.object(runner, "utc_date", return_value="2026-12-01"), self.assertRaises(AssertionError):
                runner.execute("B", out, c, frozen=False)
            self.assertTrue(runner.execute("B", out, c, frozen=False))

    def test_study_requires_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError):
                runner.execute("A", Path(tmp), clients(), frozen=False)

    def test_spend_cap_spans_folders_then_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            c = clients()
            self.preflight(out, c)
            pre = completion(out, "preflight")["spent_usd"]
            with mock.patch.object(runner, "MAX_SPEND_USD", pre + 0.5):
                self.assertFalse(runner.execute("B", out, c, frozen=False))
            self.assertEqual((completion(out, "B")["status"], completion(out, "B")["reason"]), ("PAUSED", "spend cap"))
            self.assertLessEqual(pre + completion(out, "B")["spent_usd"], pre + 0.5)
            self.assertTrue(runner.execute("B", out, c, frozen=False))
            self.assertEqual(verify.verify_study(out, "B", json.loads((out / "preflight" / "verdict.json").read_bytes()))[0].status, "COMPLETE")

    def test_quota_pauses_then_resume(self):
        state = {"quota": True}
        base = responder("google")
        next_call = counter()

        def handle(request):
            if state["quota"] and next_call() > 20:
                return error("google", 429, "RESOURCE_EXHAUSTED", "You exceeded your current quota, please check your plan and billing details.")
            return base(request)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            c = clients({"google": handle})
            self.preflight(out, c)
            self.assertFalse(runner.execute("B", out, c, frozen=False))
            self.assertEqual(completion(out, "B")["reason"], "provider quota")
            state["quota"] = False
            self.assertTrue(runner.execute("B", out, c, frozen=False))

    def test_preflight_quota_pauses_without_exclusion(self):
        state = {"quota": True}
        base = responder("moonshot")

        def handle(request):
            if state["quota"]:
                return error("moonshot", 429, "exceeded_current_quota_error", "please check your plan and billing details")
            return base(request)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            c = clients({"moonshot": handle})
            self.assertFalse(runner.execute("preflight", out, c, frozen=False))
            self.assertFalse((out / "preflight" / "verdict.json").exists())
            state["quota"] = False
            verdict = self.preflight(out, c)
            self.assertEqual(verdict["models"]["kimi-k3"]["status"], "PASS")
            self.assertEqual(verify.verify_preflight(out)[1], verdict)

    def test_transient_failures_retry(self):
        base = responder("openai", delay=0.001)
        next_call = counter()
        local = threading.local()

        def handle(request):
            call = next_call()
            if getattr(local, "failed", False):
                local.failed = False
                return base(request)
            if call > 30 and call % 7 == 0:
                local.failed = True
                raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
            if call > 30 and call % 13 == 0:
                local.failed = True
                raise httpx.ReadTimeout("The read operation timed out")
            if call > 30 and call % 11 == 0:
                local.failed = True
                return error("openai", 503, "server_error", "overloaded")
            return base(request)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(runner, "retry_sleep"):
            out = Path(tmp)
            c = clients({"openai": handle})
            verdict = self.preflight(out, c)
            self.assertTrue(runner.execute("B", out, c, frozen=False))
            ledger, _ = verify.verify_study(out, "B", verdict)
            self.assertGreater(sum(1 for e in events(out, "B") if e["event"] == "retry_wait"), 0)
            classes = [json.loads(p.read_bytes())["class"] for p in (out / "studyB" / "attempts").rglob("classification.json")]
            self.assertIn("E", classes)
            self.assertFalse(any(r["class"] == "E" for r in ledger.definitive.values()))

    def test_sigint_drains_then_resume(self):
        base = responder("anthropic", delay=0.002)
        next_call = counter()
        state = {"armed": False}

        def handle(request):
            if state["armed"] and next_call() == 100:
                os.kill(os.getpid(), signal.SIGINT)
            return base(request)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            c = clients({"anthropic": handle})
            self.preflight(out, c)
            state["armed"] = True
            self.assertFalse(runner.execute("B", out, c, frozen=False))
            self.assertEqual(completion(out, "B")["reason"], "interrupted")
            self.assertTrue(runner.execute("B", out, c, frozen=False))

    def test_model_mismatch_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.preflight(out)
            c = clients({"moonshot": responder("moonshot", returned="kimi-other")})
            self.assertFalse(runner.execute("B", out, c, frozen=False))
            self.assertEqual(completion(out, "B")["status"], "INCONCLUSIVE")
            with self.assertRaises(AssertionError):
                runner.execute("B", out, c, frozen=False)

    def test_preflight_alias_is_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            verdict = self.preflight(out, clients({"google": responder("google", returned="gemini-3.6-flash")}))
            self.assertEqual({m: verdict["models"][m]["status"] for m in MODELS["google"]},
                             {"gemini-3-flash-preview": "OP", "gemini-3.6-flash": "PASS", "gemini-4-argon": "OP"})

    def test_credentials_from_environment(self):
        env = {name: "" for name in frozen.CREDENTIAL_ENV.values()}
        with mock.patch.dict(os.environ, env):
            with self.assertRaises(AssertionError):
                runner.credentials()
        env = {name: "k" + name for name in frozen.CREDENTIAL_ENV.values()}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(runner.credentials()["google"], "kGEMINI_API_KEY")

    def test_unpriced_models_refuse_to_run(self):
        with mock.patch.dict(frozen.PRICES_USD_PER_MTOK, {"kimi-k3": None}), tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError):
                runner.execute("preflight", Path(tmp), clients(), frozen=False)


if __name__ == "__main__":
    unittest.main()
