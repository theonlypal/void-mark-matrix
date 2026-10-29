"""Offline fixtures for the per-vendor request builders, extractors and the cross-provider classification.

Every fixture body is synthetic unit-test data, never a model observation.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import vendors
import xclassify
from classifier import classify
from frozen import EXACT_TARGETS, MODEL_CONFIG, request, load_schedule, usage_nano_usd, milli_price
import verify


def run(vendor, body, status=200, experiment=2):
    raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
    return xclassify.classify_attempt(experiment, vendor, status, raw)[1]


def chat(content="x", finish="stop", model="gpt-5.2-2025-12-11", **message):
    message = dict(message, role="assistant")
    if content is not ...:
        message["content"] = content
    return {"id": "chatcmpl-synthetic", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 5, "total_tokens": 35}}


def gemini(parts, finish="STOP", model="gemini-4-argon", content=True, **candidate):
    candidate = dict(candidate, index=0, finishReason=finish)
    if content:
        candidate["content"] = {"role": "model"} if parts is None else {"role": "model", "parts": parts}
    return {"candidates": [candidate], "modelVersion": model, "responseId": "resp-synthetic",
            "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 4, "thoughtsTokenCount": 7}}


def messages(content, stop="end_turn", model="claude-fable-5-1"):
    return {"id": "msg_synthetic", "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 30, "output_tokens": 5}}


class Requests(unittest.TestCase):
    def test_shapes(self):
        b = request("A", {"slot_id": "x", "vendor": "openai", "model": "gpt-5.2-2025-12-11", "input": "U"}, "t0")[1]
        self.assertEqual(b["reasoning_effort"], "none")
        self.assertEqual(b["temperature"], 0)
        url, b = vendors.build_request("openai", "gpt-6-astra", "S", "U", 4000, None, MODEL_CONFIG["gpt-6-astra"]["reasoning"])
        self.assertEqual(url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(b, {"model": "gpt-6-astra", "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}],
                             "max_completion_tokens": 4000, "reasoning_effort": "low"})
        url, b = vendors.build_request("moonshot", "kimi-k3", "S", "U", 16000, None, MODEL_CONFIG["kimi-k3"]["reasoning"])
        self.assertEqual(url, "https://api.moonshot.ai/v1/chat/completions")
        self.assertEqual(b, {"model": "kimi-k3", "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}],
                             "max_completion_tokens": 16000})
        url, b = vendors.build_request("google", "gemini-4-argon", "S", "U", 4000, None, MODEL_CONFIG["gemini-4-argon"]["reasoning"])
        self.assertEqual(url, "https://generativelanguage.googleapis.com/v1beta/models/gemini-4-argon:generateContent")
        self.assertEqual(b, {"contents": [{"role": "user", "parts": [{"text": "U"}]}], "systemInstruction": {"parts": [{"text": "S"}]},
                             "generationConfig": {"maxOutputTokens": 4000, "thinkingConfig": {"thinkingLevel": "low"}}})
        url, b = vendors.build_request("google", "gemini-3-flash-preview", "S", "U", 4000, 0, MODEL_CONFIG["gemini-3-flash-preview"]["reasoning"])
        self.assertEqual(b["generationConfig"], {"maxOutputTokens": 4000, "temperature": 0, "thinkingConfig": {"thinkingLevel": "minimal"}})
        url, b = vendors.build_request("anthropic", "claude-opus-4-6", "S", "U", 4000, None, {})
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(b, {"model": "claude-opus-4-6", "max_tokens": 4000, "system": "S", "messages": [{"role": "user", "content": "U"}]})

    def test_frozen_settings_in_every_scheduled_body(self):
        for study in ("A", "B"):
            for slot in load_schedule(study):
                for variant in slot["request_sha256"]:
                    b = request(study, slot, variant)[1]
                    cfg = MODEL_CONFIG[slot["model"]]
                    config = b.get("generationConfig", {})
                    if slot["vendor"] == "google":
                        self.assertEqual(config["thinkingConfig"], cfg["reasoning"])
                        self.assertFalse({"topP", "topK", "candidateCount", "seed"} & set(config))
                    else:
                        self.assertEqual({k: b[k] for k in cfg["reasoning"]}, cfg["reasoning"])
                        self.assertFalse({"thinking", "output_config", "stream", "top_p", "tools"} & set(b))
                    if cfg["temperature"] == "omit":
                        self.assertNotIn("temperature", b)
                        self.assertNotIn("temperature", config)
                    self.assertNotIn("continuationToken", b)

    def test_headers(self):
        self.assertEqual(vendors.headers("anthropic", "k"), {"x-api-key": "k", "anthropic-version": "2023-06-01"})
        self.assertEqual(vendors.headers("openai", "k"), {"authorization": "Bearer k"})
        self.assertEqual(vendors.headers("moonshot", "k"), {"authorization": "Bearer k"})
        self.assertEqual(vendors.headers("google", "k"), {"x-goog-api-key": "k"})


class ChatCompletions(unittest.TestCase):
    def test_text_container_states(self):
        for vendor in ("openai", "moonshot"):
            self.assertEqual(run(vendor, chat(""))["class"], "V0")
            self.assertEqual(run(vendor, chat(None))["class"], "V2")
            self.assertEqual(run(vendor, chat(...))["class"], "V2")
            self.assertEqual(run(vendor, chat("", "length"))["class"], "V1")
            self.assertEqual(run(vendor, chat(None, "length"))["class"], "V1")
            self.assertEqual(run(vendor, chat("", "unlisted_stop"))["class"], "VU")

    def test_visible_near_void_refusal(self):
        for vendor in ("openai", "moonshot"):
            r = run(vendor, chat("Hello."))
            self.assertEqual((r["class"], r["returned_model"], r["response_id"], r["stop_reason"]),
                             ("R", "gpt-5.2-2025-12-11", "chatcmpl-synthetic", "end_turn"))
            self.assertEqual(r["usage"], {"input_tokens": 30, "output_tokens": 5})
            self.assertEqual(run(vendor, chat("​"))["class"], "NV")
            self.assertEqual(run(vendor, chat(" "))["class"], "NV")
            self.assertEqual(run(vendor, chat("..."))["class"], "NV")
            self.assertEqual(run(vendor, chat(None, refusal="I can't."))["class"], "RF")
            self.assertEqual(run(vendor, chat("", refusal=None))["class"], "V0")

    def test_safety_block_is_sb(self):
        for vendor in ("openai", "moonshot"):
            for content in ("", None, "partial"):
                r = run(vendor, chat(content, "content_filter"))
                self.assertEqual((r["class"], r["void"]), ("SB", False))
                self.assertEqual(r["signals"]["safety_block"], "finish_reason content_filter")
            self.assertEqual(run(vendor, chat(None, "content_filter", refusal="no"))["class"], "SB")

    def test_tools(self):
        for vendor in ("openai", "moonshot"):
            r = run(vendor, chat(None, "tool_calls", tool_calls=[{"id": "c", "type": "function"}]))
            self.assertEqual(r["class"], "TC")
            r = run(vendor, chat(None, "tool_calls"))
            self.assertEqual((r["class"], r["upstream_class"], r["void"]), ("PI", "VU", False))
            self.assertEqual(run(vendor, chat("", "function_call"))["class"], "PI")

    def test_unknown_output_parts(self):
        r = run("openai", chat([{"type": "output_audio"}]))
        self.assertEqual((r["class"], r["upstream_class"]), ("PI", "V2"))
        self.assertEqual(r["signals"]["unknown_parts"], ["message.content:list"])
        self.assertEqual(run("openai", chat("", audio={"id": "a"}))["class"], "PI")
        self.assertEqual(run("openai", chat("", audio=None))["class"], "V0")

    def test_moonshot_reasoning_is_not_text(self):
        r = run("moonshot", chat("", reasoning_content="internal", model="kimi-k3"))
        self.assertEqual((r["class"], r["block_types"], r["visible_bytes"]), ("V0", ["reasoning_content", "text"], 0))
        r = run("moonshot", chat(None, "length", reasoning_content="internal", model="kimi-k3"))
        self.assertEqual((r["class"], r["text_container_present"]), ("V1", False))
        raw = json.dumps(chat("", reasoning_content="internal")).encode()
        self.assertNotIn(b"internal", vendors.normalize("moonshot", 200, raw))

    def test_study_b_targets_and_variants(self):
        for name in ("T1", "T0", "HE", "SHART", "SHAMS"):
            self.assertEqual(run("openai", chat(EXACT_TARGETS[name]), experiment=3)["class"], name)
        patah = "شַׁרְט"
        self.assertEqual(run("openai", chat(patah), experiment=3)["class"], "MX")
        self.assertEqual(run("openai", chat(EXACT_TARGETS["T1"] + "\n"), experiment=3)["class"], "MX")
        self.assertEqual(run("openai", chat("not parsed"), experiment=3)["class"], "OT")
        self.assertEqual(run("openai", chat(" "), experiment=3)["class"], "OT")
        self.assertEqual(run("openai", chat(""), experiment=3)["class"], "V0")
        self.assertEqual(run("openai", chat("", "content_filter"), experiment=3)["class"], "SB")

    def test_errors(self):
        quota = {"error": {"message": "You exceeded your current quota, please check your plan and billing details.",
                           "type": "insufficient_quota", "code": "insufficient_quota"}}
        self.assertEqual(run("openai", quota, 429)["class"], "QE")
        rate = {"error": {"message": "Rate limit reached for requests", "type": "requests", "code": "rate_limit_exceeded"}}
        self.assertEqual(run("openai", rate, 429)["class"], "E")
        bad = {"error": {"message": "Unsupported value: 'temperature' does not support 0 with this model.",
                         "type": "invalid_request_error", "param": "temperature", "code": "unsupported_value"}}
        r = run("openai", bad, 400)
        self.assertEqual((r["class"], r["provider_error_type"]), ("PI", "invalid_request_error"))
        self.assertEqual(run("moonshot", {"error": {"type": "exceeded_current_quota_error",
                                                    "message": "Your account is suspended, please check your plan and billing details"}}, 429)["class"], "QE")
        self.assertEqual(run("openai", {"error": {"message": "The model does not exist", "type": "invalid_request_error"}}, 404)["class"], "PI")
        self.assertEqual(run("openai", {"error": {"message": "timeout", "type": "server_error"}}, 504)["class"], "E")

    def test_malformed(self):
        self.assertEqual(run("openai", {"choices": []})["class"], "E")
        self.assertEqual(run("openai", {"choices": [{"message": {"content": "x"}}]})["class"], "E")
        two = chat("x")
        two["choices"].append(two["choices"][0])
        self.assertEqual(run("openai", two)["class"], "E")
        self.assertEqual(run("openai", b"not json")["class"], "E")
        self.assertEqual(xclassify.classify_attempt(2, "openai", None, b"")[1]["class"], "E")


class Gemini(unittest.TestCase):
    def test_text_container_states(self):
        self.assertEqual(run("google", gemini([{"text": ""}]))["class"], "V0")
        self.assertEqual(run("google", gemini([]))["class"], "V2")
        self.assertEqual(run("google", gemini(None))["class"], "V2")
        self.assertEqual(run("google", gemini(None, content=False))["class"], "V2")
        self.assertEqual(run("google", {"candidates": [{"content": {}, "finishReason": "STOP", "index": 0}],
                                        "modelVersion": "gemini-3.6-flash", "responseId": "r"})["class"], "V2")
        self.assertEqual(run("google", gemini(None, "MAX_TOKENS"))["class"], "V1")
        self.assertEqual(run("google", gemini([{"text": ""}], "OTHER"))["class"], "VU")

    def test_thought_only_and_signatures(self):
        self.assertEqual(run("google", gemini([{"text": "", "thought": True, "thoughtSignature": "s"}]))["class"], "V2")
        self.assertEqual(run("google", gemini([{"text": "plan", "thought": True}], "MAX_TOKENS"))["class"], "V1")
        self.assertEqual(run("google", gemini([{"text": "", "thoughtSignature": "s"}]))["class"], "V0")
        r = run("google", gemini([{"text": "plan", "thought": True}, {"text": "Hello."}]))
        self.assertEqual((r["class"], r["block_types"], r["content_utf8_hex"]), ("R", ["thought", "text"], "Hello.".encode().hex()))
        self.assertEqual((r["returned_model"], r["response_id"]), ("gemini-4-argon", "resp-synthetic"))
        self.assertEqual(r["usage"], {"input_tokens": 30, "output_tokens": 11})
        self.assertEqual(run("google", gemini([{"text": "a"}, {"text": "b"}]))["content_utf8_hex"], b"ab".hex())

    def test_unknown_parts(self):
        r = run("google", gemini([{"inlineData": {"mimeType": "image/png", "data": ""}}]))
        self.assertEqual((r["class"], r["upstream_class"], r["void"]), ("PI", "V2", False))
        self.assertEqual(r["signals"]["unknown_parts"], ["part:inlineData"])
        self.assertEqual(run("google", gemini([{"thoughtSignature": "s"}]))["class"], "PI")
        self.assertEqual(run("google", gemini([{"text": "x"}, {"fileData": {}}]))["class"], "PI")

    def test_safety_with_and_without_candidate(self):
        for parts in (None, [], [{"text": "partial"}]):
            for finish in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"):
                r = run("google", gemini(parts, finish))
                self.assertEqual((r["class"], r["void"]), ("SB", False), (parts, finish))
        rated = gemini([], "STOP", safetyRatings=[{"category": "HARM_CATEGORY_HARASSMENT", "probability": "HIGH", "blocked": True}])
        self.assertEqual(run("google", rated)["class"], "SB")
        r = run("google", {"promptFeedback": {"blockReason": "SAFETY"}, "modelVersion": "gemini-4-argon", "responseId": "r"})
        self.assertEqual((r["class"], r["model_completion"], r["signals"]["safety_block"]), ("SB", True, "promptFeedback.blockReason SAFETY"))
        with_candidate = dict(gemini([{"text": "x"}]), promptFeedback={"blockReason": "OTHER"})
        self.assertEqual(run("google", with_candidate)["class"], "SB")
        unspecified = {"promptFeedback": {"blockReason": "BLOCK_REASON_UNSPECIFIED"}, "modelVersion": "gemini-4-argon"}
        self.assertEqual(run("google", unspecified)["class"], "E")

    def test_missing_candidates_are_malformed(self):
        self.assertEqual(run("google", {"modelVersion": "gemini-4-argon", "responseId": "r"})["class"], "E")
        self.assertEqual(run("google", {"candidates": [], "modelVersion": "gemini-4-argon"})["class"], "E")
        two = gemini([{"text": "x"}])
        two["candidates"].append(two["candidates"][0])
        self.assertEqual(run("google", two)["class"], "E")

    def test_continuation(self):
        documented = {"candidates": [{"content": {"role": "model", "parts": [{"text": ""}]}, "finishReason": "CONTINUATION",
                                      "continuationToken": "CiQ4ZmQ3..."}],
                      "modelVersion": "gemini-4-argon", "responseId": "r",
                      "usageMetadata": {"promptTokenCount": 142, "candidatesTokenCount": 0, "thoughtsTokenCount": 32768,
                                        "totalTokenCount": 32910}}
        r = run("google", documented)
        self.assertEqual((r["class"], r["upstream_class"], r["void"], r["model_completion"]), ("CN", "VU", False, True))
        self.assertEqual(r["usage"], {"input_tokens": 142, "output_tokens": 32768})
        self.assertEqual(run("google", gemini([{"text": "partial"}], "CONTINUATION"))["class"], "CN")
        self.assertEqual(run("google", gemini([{"text": "x"}], "CONTINUATION"), experiment=3)["class"], "CN")

    def test_tools(self):
        self.assertEqual(run("google", gemini([{"functionCall": {"name": "f"}}]))["class"], "TC")
        self.assertEqual(run("google", gemini([{"functionCall": {"name": "f"}}], "MALFORMED_FUNCTION_CALL"))["class"], "TC")
        for finish in ("MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", "TOO_MANY_TOOL_CALLS"):
            r = run("google", gemini(None, finish))
            self.assertEqual((r["class"], r["void"]), ("PI", False))

    def test_errors_and_malformed(self):
        err = {"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details.",
                         "status": "RESOURCE_EXHAUSTED"}}
        r = run("google", err, 429)
        self.assertEqual((r["class"], r["provider_error_type"]), ("QE", "RESOURCE_EXHAUSTED"))
        self.assertEqual(run("google", {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}, 503)["class"], "E")
        self.assertEqual(run("google", {"error": {"code": 504, "message": "Deadline exceeded", "status": "DEADLINE_EXCEEDED"}}, 504)["class"], "E")
        self.assertEqual(run("google", {"error": {"code": 404, "message": "not found", "status": "NOT_FOUND"}}, 404)["class"], "PI")
        self.assertEqual(run("google", {"candidates": [{"content": {"parts": [{"text": "x"}]}}]})["class"], "E")
        self.assertEqual(run("google", gemini([{"text": 5}]))["class"], "E")
        self.assertEqual(run("google", gemini(["x"]))["class"], "E")
        self.assertEqual(run("google", {"candidates": [{"content": "x", "finishReason": "STOP"}]})["class"], "E")


class Anthropic(unittest.TestCase):
    def test_pass_through_equals_upstream(self):
        cases = [messages([]), messages([{"type": "text", "text": ""}]), messages([{"type": "text", "text": "Hi"}]),
                 messages([{"type": "thinking", "thinking": "", "signature": "s"}]),
                 messages([{"type": "thinking", "thinking": "", "signature": "s"}], "max_tokens"),
                 messages([{"type": "redacted_thinking", "data": "d"}, {"type": "text", "text": "​"}]),
                 messages([{"type": "text", "text": "x"}], "refusal"), messages([], "refusal"),
                 messages([{"type": "tool_use", "id": "t", "name": "f", "input": {}}], "tool_use"),
                 messages([], "pause_turn"), {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}]
        expected = ["V2", "V0", "R", "V2", "V1", "NV", "RF", "RF", "TC", "VU", "E"]
        for body, cls in zip(cases, expected):
            raw = json.dumps(body).encode()
            mapped, r = xclassify.classify_attempt(2, "anthropic", 200 if "error" not in body else 529, raw)
            self.assertIs(mapped, raw)
            self.assertEqual(r["class"], cls, body)
            upstream = classify(2, 200 if "error" not in body else 529, raw)
            self.assertEqual({k: v for k, v in r.items() if k in upstream}, upstream)
            self.assertEqual(r["upstream_class"], r["class"])

    def test_unknown_block_type(self):
        r = run("anthropic", messages([{"type": "image_output", "data": ""}]))
        self.assertEqual((r["class"], r["upstream_class"]), ("PI", "V2"))


class Charges(unittest.TestCase):
    def test_absent_usage_keeps_reservation(self):
        meta = {"http_status": 200, "transport_error": None}
        self.assertEqual(verify.charge(meta, {"usage": None}, 777, "kimi-k3"), ("reservation", 777))
        self.assertEqual(verify.charge({"http_status": None, "transport_error": {"type": "ReadTimeout"}}, {"usage": None}, 777, "kimi-k3"),
                         ("reservation", 777))
        self.assertEqual(verify.charge({"http_status": 400, "transport_error": None}, {"usage": None}, 777, "kimi-k3"), ("none", 0))

    def test_usage_at_input_ceiling(self):
        cost = usage_nano_usd("gpt-6-astra", {"input_tokens": 100, "output_tokens": 10})
        self.assertEqual(cost, 100 * 25_000 + 10 * 50_000)
        self.assertEqual(milli_price("kimi-k3", "input_ceiling"), 6000)
        self.assertIsNone(usage_nano_usd("kimi-k3", {"input_tokens": 1}))


if __name__ == "__main__":
    unittest.main()
