"""Per-vendor request builders and response-field extractors. Pure functions; no network operations.

Each extractor maps a vendor response onto the Anthropic Messages fields read by the upstream classifier:
id, model, type, role, content blocks, stop_reason, usage and error.type/error.message. Anthropic bytes pass
through unchanged. Observations the upstream classifier has no field for (provider safety blocks, non-final
continuation, unknown output parts, tool terminations without a tool payload) are returned as separate signals.
The vendor response bytes are persisted unaltered; the mapped bytes are persisted beside them.
"""
import json

ANTHROPIC_VERSION = "2023-06-01"
ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "google": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    "moonshot": "https://api.moonshot.ai/v1/chat/completions",
}
READ_TIMEOUT_SECONDS = {"openai": 600, "anthropic": 600, "google": 1200, "moonshot": 600}

STOP_MAP = {
    "openai": {"stop": "end_turn", "length": "max_tokens"},
    "moonshot": {"stop": "end_turn", "length": "max_tokens"},
    "google": {"STOP": "end_turn", "MAX_TOKENS": "max_tokens"},
}
CHAT_SAFETY_STOPS = {"content_filter"}
CHAT_TOOL_STOPS = {"tool_calls", "function_call"}
GEMINI_SAFETY_STOPS = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY",
                       "IMAGE_PROHIBITED_CONTENT", "IMAGE_RECITATION"}
GEMINI_TOOL_STOPS = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", "TOO_MANY_TOOL_CALLS"}
GEMINI_CONTINUATION_STOP = "CONTINUATION"
GEMINI_TOOL_PART_KEYS = {"functionCall", "functionResponse", "executableCode", "codeExecutionResult"}
ANTHROPIC_BLOCK_TYPES = {"text", "thinking", "redacted_thinking", "tool_use", "server_tool_use"}

FIELDS = {
    "openai": {"text": "choices[0].message.content (string; null or absent is an absent text container; any other type is an unknown output part)",
               "refusal": "choices[0].message.refusal (nonempty string sets stop_reason refusal)",
               "tool": "choices[0].message.tool_calls or function_call (nonempty adds a tool_use block)",
               "audio": "choices[0].message.audio (non-null is an unknown output part)",
               "stop": "choices[0].finish_reason", "model": "model", "id": "id",
               "usage": "usage.prompt_tokens as input_tokens, usage.completion_tokens as output_tokens",
               "error": "error.type and error.message"},
    "anthropic": {"mapping": "response bytes passed to the classifier unchanged",
                  "unknown": "content block types other than " + ", ".join(sorted(ANTHROPIC_BLOCK_TYPES)) + " are unknown output parts"},
    "google": {"candidate": "candidates must hold exactly one candidate; an absent content object is an absent text container",
               "text": "candidates[0].content.parts[*].text where thought is not true (no text part is an absent text container)",
               "thought": "parts with thought true become thought blocks, never text",
               "tool": "parts with functionCall, functionResponse, executableCode or codeExecutionResult become tool_use blocks",
               "unknown": "parts with none of text, thought or a tool key are unknown output parts",
               "stop": "candidates[0].finishReason", "model": "modelVersion", "id": "responseId",
               "prompt_block": "no candidates and promptFeedback.blockReason set: empty content, safety signal",
               "usage": "usageMetadata.promptTokenCount as input_tokens, candidatesTokenCount + thoughtsTokenCount as output_tokens",
               "error": "error.status as error.type, error.message"},
    "moonshot": {"text": "choices[0].message.content (string; null or absent is an absent text container; any other type is an unknown output part)",
                 "reasoning": "choices[0].message.reasoning_content retained in the raw bytes; becomes a reasoning_content block, never text",
                 "refusal": "choices[0].message.refusal (nonempty string sets stop_reason refusal)",
                 "tool": "choices[0].message.tool_calls or function_call (nonempty adds a tool_use block)",
                 "stop": "choices[0].finish_reason", "model": "model", "id": "id",
                 "usage": "usage.prompt_tokens as input_tokens, usage.completion_tokens as output_tokens",
                 "error": "error.type and error.message"},
}
SIGNALS = {
    "safety_block": "OpenAI and Moonshot finish_reason content_filter; Gemini finishReason in " + ", ".join(sorted(GEMINI_SAFETY_STOPS))
                    + ", a candidate safety rating with blocked true, or promptFeedback.blockReason other than BLOCK_REASON_UNSPECIFIED",
    "continuation": "Gemini finishReason CONTINUATION (non-final; no continuation request is sent)",
    "unknown_parts": "output parts or blocks the extractor cannot represent",
    "tool_termination_without_payload": "finish_reason tool_calls or function_call, or Gemini finishReason in "
                                        + ", ".join(sorted(GEMINI_TOOL_STOPS)) + ", without a tool payload",
}


def build_request(vendor, model, system, user, max_tokens, temperature, reasoning):
    """URL and JSON body. temperature None omits the field. reasoning holds the model's frozen reasoning fields."""
    if vendor == "anthropic":
        assert not reasoning
        body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": user}]}
        if system is not None:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = temperature
        return ENDPOINTS[vendor], body
    if vendor in ("openai", "moonshot"):
        messages = ([{"role": "system", "content": system}] if system is not None else []) + [{"role": "user", "content": user}]
        body = {"model": model, "messages": messages, "max_completion_tokens": max_tokens}
        body.update(reasoning)
        if temperature is not None:
            body["temperature"] = temperature
        return ENDPOINTS[vendor], body
    if vendor == "google":
        config = {"maxOutputTokens": max_tokens}
        if reasoning:
            config["thinkingConfig"] = dict(reasoning)
        if temperature is not None:
            config["temperature"] = temperature
        body = {"contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": config}
        if system is not None:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return ENDPOINTS[vendor].format(model=model), body
    raise ValueError(vendor)


def headers(vendor, key):
    if vendor == "anthropic":
        return {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    if vendor == "google":
        return {"x-goog-api-key": key}
    return {"authorization": "Bearer " + key}


CREDENTIAL_HEADERS = {"x-api-key", "x-goog-api-key", "authorization"}


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def no_signals():
    return {"safety_block": None, "continuation": False, "unknown_parts": [], "tool_termination_without_payload": None}


def chat_message(vendor, obj, signals):
    usage = obj.get("usage")
    env = {"id": obj.get("id"), "model": obj.get("model"), "type": "message", "role": "assistant", "stop_sequence": None}
    if isinstance(usage, dict) and count(usage.get("prompt_tokens")) is not None and count(usage.get("completion_tokens")) is not None:
        env["usage"] = {"input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"]}
    choices = obj.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return env
    message, stop = choices[0].get("message"), choices[0].get("finish_reason")
    if not isinstance(message, dict) or not isinstance(stop, str):
        return env
    content = []
    if vendor == "moonshot" and message.get("reasoning_content") is not None:
        content.append({"type": "reasoning_content"})
    text = message.get("content")
    if isinstance(text, str):
        content.append({"type": "text", "text": text})
    elif text is not None:
        content.append({"type": "unknown"})
        signals["unknown_parts"].append("message.content:" + type(text).__name__)
    if message.get("audio") is not None:
        content.append({"type": "unknown"})
        signals["unknown_parts"].append("message.audio")
    tool = bool(message.get("tool_calls") or message.get("function_call"))
    if tool:
        content.append({"type": "tool_use"})
    if stop in CHAT_SAFETY_STOPS:
        signals["safety_block"] = "finish_reason " + stop
    if stop in CHAT_TOOL_STOPS and not tool:
        signals["tool_termination_without_payload"] = "finish_reason " + stop
    refusal = message.get("refusal")
    env["content"] = content
    env["stop_reason"] = "refusal" if isinstance(refusal, str) and refusal else STOP_MAP[vendor].get(stop, stop)
    return env


def prompt_block(obj):
    feedback = obj.get("promptFeedback")
    reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
    return reason if isinstance(reason, str) and reason not in ("", "BLOCK_REASON_UNSPECIFIED") else None


def rating_blocked(ratings):
    return isinstance(ratings, list) and any(isinstance(r, dict) and r.get("blocked") is True for r in ratings)


def gemini_message(obj, signals):
    usage = obj.get("usageMetadata")
    env = {"id": obj.get("responseId"), "model": obj.get("modelVersion"), "type": "message", "role": "assistant",
           "stop_sequence": None}
    if isinstance(usage, dict) and count(usage.get("promptTokenCount")) is not None:
        outputs = [count(usage.get(k)) for k in ("candidatesTokenCount", "thoughtsTokenCount")]
        env["usage"] = {"input_tokens": usage["promptTokenCount"], "output_tokens": sum(n or 0 for n in outputs)}
    blocked = prompt_block(obj)
    if blocked:
        signals["safety_block"] = "promptFeedback.blockReason " + blocked
    candidates = obj.get("candidates")
    if not candidates:
        if blocked:
            env.update(content=[], stop_reason="PROMPT_BLOCKED")
        return env
    if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
        return env
    candidate = candidates[0]
    stop, body = candidate.get("finishReason"), candidate.get("content", {})
    if not isinstance(stop, str) or not stop or not isinstance(body, dict):
        return env
    parts = body.get("parts", [])
    if not isinstance(parts, list):
        return env
    content, tool = [], False
    for part in parts:
        if not isinstance(part, dict):
            return env
        if "text" in part and not isinstance(part["text"], str):
            return env
        if part.get("thought") is True:
            content.append({"type": "thought"})
        elif GEMINI_TOOL_PART_KEYS & set(part):
            content.append({"type": "tool_use"})
            tool = True
        elif "text" in part:
            content.append({"type": "text", "text": part["text"]})
        else:
            content.append({"type": "unknown"})
            signals["unknown_parts"].append("part:" + ",".join(sorted(part)))
    if stop in GEMINI_SAFETY_STOPS:
        signals["safety_block"] = "finishReason " + stop
    elif rating_blocked(candidate.get("safetyRatings")):
        signals["safety_block"] = "safetyRatings blocked"
    if stop == GEMINI_CONTINUATION_STOP:
        signals["continuation"] = True
    if stop in GEMINI_TOOL_STOPS and not tool:
        signals["tool_termination_without_payload"] = "finishReason " + stop
    env.update(content=content, stop_reason=STOP_MAP["google"].get(stop, stop))
    return env


def anthropic_signals(http_status, raw, signals):
    if not 200 <= http_status < 300:
        return
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError):
        return
    content = obj.get("content") if isinstance(obj, dict) else None
    for block in content if isinstance(content, list) else []:
        kind = block.get("type") if isinstance(block, dict) else None
        if isinstance(kind, str) and kind not in ANTHROPIC_BLOCK_TYPES:
            signals["unknown_parts"].append("block:" + kind)


def error_envelope(vendor, obj):
    error = obj.get("error") if isinstance(obj, dict) else None
    if not isinstance(error, dict):
        return obj
    kind = error.get("status") if vendor == "google" else error.get("type")
    return {"error": {"type": kind if isinstance(kind, str) else "", "message": error.get("message") if isinstance(error.get("message"), str) else ""}}


def extract(vendor, http_status, raw):
    """Bytes for the upstream classifier and the extension signals. Unparseable bodies pass through unchanged and classify as E."""
    signals = no_signals()
    if http_status is None:
        return raw, signals
    if vendor == "anthropic":
        anthropic_signals(http_status, raw, signals)
        return raw, signals
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError):
        return raw, signals
    if not isinstance(obj, dict):
        return raw, signals
    if not 200 <= http_status < 300:
        mapped = error_envelope(vendor, obj)
    elif vendor == "google":
        mapped = gemini_message(obj, signals)
    else:
        mapped = chat_message(vendor, obj, signals)
    return json.dumps(mapped, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"), signals


def normalize(vendor, http_status, raw):
    return extract(vendor, http_status, raw)[0]
