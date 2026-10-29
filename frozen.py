"""Frozen constants, request construction and schedule generation. No network operations."""
import hashlib
import json
import random
import re
from decimal import Decimal
from pathlib import Path
import vendors

ROOT = Path(__file__).resolve().parent
TITLE = "The Void and the Mark: Null Embodiment and Prerequisite Crossover Across Historical and Current Frontier Models"
AUTHOR = "Rayan Pal"
FROZEN_TAG = "v1.0.0"
PINNED = {"httpx": "0.28.1", "regex": "2025.11.3"}
CONCURRENCY_PER_VENDOR = 4

VENDORS = ("openai", "anthropic", "google", "moonshot")
MODELS = {
    "openai": ["gpt-5.2-2025-12-11", "gpt-5.4-2026-03-05", "gpt-5.5-2026-04-23", "gpt-6-astra"],
    "anthropic": ["claude-opus-4-5-20251101", "claude-opus-4-6", "claude-fable-5-1"],
    "google": ["gemini-3-flash-preview", "gemini-3.6-flash", "gemini-4-argon"],
    "moonshot": ["kimi-k3"],
}
VENDOR_OF = {m: v for v in VENDORS for m in MODELS[v]}
CREDENTIAL_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GEMINI_API_KEY",
                  "moonshot": "MOONSHOT_API_KEY"}

# Per-model request settings. temperature "probe": preflight tests temperature 0 and omission, Study A uses 0 where the
# temperature-0 check passes. temperature "omit": the provider documents the field as rejected, ignored or fixed.
# reasoning: extra top-level request fields (OpenAI, Moonshot) or generationConfig.thinkingConfig (Google).
MODEL_CONFIG = {
    "gpt-5.2-2025-12-11": {"identifier": "dated snapshot", "temperature": "probe", "reasoning": {"reasoning_effort": "none"},
                           "reasoning_note": "reasoning_effort none (supported: none, low, medium, high, xhigh; default none)"},
    "gpt-5.4-2026-03-05": {"identifier": "dated snapshot", "temperature": "probe", "reasoning": {"reasoning_effort": "none"},
                           "reasoning_note": "reasoning_effort none (supported: none, low, medium, high, xhigh; default none)"},
    "gpt-5.5-2026-04-23": {"identifier": "dated snapshot", "temperature": "probe", "reasoning": {"reasoning_effort": "none"},
                           "reasoning_note": "reasoning_effort none (supported: none, low, medium, high, xhigh; default medium)"},
    "gpt-6-astra": {"identifier": "served identifier", "temperature": "omit", "reasoning": {"reasoning_effort": "low"},
                    "reasoning_note": "reasoning_effort low, the lowest supported value (supported: low, medium, high, xhigh, max; none unsupported); temperature unsupported when reasoning effort is not none"},
    "claude-opus-4-5-20251101": {"identifier": "dated snapshot", "temperature": "probe", "reasoning": {},
                                 "reasoning_note": "thinking not requested (provider default: off)"},
    "claude-opus-4-6": {"identifier": "served identifier", "temperature": "probe", "reasoning": {},
                        "reasoning_note": "thinking not requested (provider default: off)"},
    "claude-fable-5-1": {"identifier": "served identifier", "temperature": "omit", "reasoning": {},
                         "reasoning_note": "no thinking or effort field sent; provider default: adaptive thinking always on, effort high; non-default temperature returns HTTP 400"},
    "gemini-3-flash-preview": {"identifier": "preview identifier", "temperature": "probe", "reasoning": {"thinkingLevel": "minimal"},
                               "reasoning_note": "thinkingLevel minimal, the lowest supported level (supported: minimal, low, medium, high; default high); minimal is not zero thinking"},
    "gemini-3.6-flash": {"identifier": "served identifier", "temperature": "omit", "reasoning": {"thinkingLevel": "minimal"},
                         "reasoning_note": "thinkingLevel minimal, the lowest supported level (supported: minimal, low, medium, high; default medium); temperature, top_p and top_k are ignored"},
    "gemini-4-argon": {"identifier": "served identifier", "temperature": "omit", "reasoning": {"thinkingLevel": "low"},
                       "reasoning_note": "thinkingLevel low, the lowest supported level (supported: low, medium, high; default medium); minimal unsupported; temperature, top_p and top_k are ignored"},
    "kimi-k3": {"identifier": "served identifier", "temperature": "omit", "reasoning": {},
                "reasoning_note": "reasoning_effort not sent; provider default max (supported: low, high, max); thinking always on; temperature, top_p, n fixed and omitted"},
}

MAX_SPEND_USD = 400
RESERVED_INPUT_TOKENS = 2000
# USD per million tokens. input_ceiling is the highest documented input-side rate (base input or cache write); every
# input-side token is charged at input_ceiling. output covers thinking tokens. valid_through: last UTC date of the rate.
PRICES_USD_PER_MTOK = {
    "gpt-5.2-2025-12-11": {"input": "1.75", "input_ceiling": "1.75", "output": "14", "valid_through": None},
    "gpt-5.4-2026-03-05": {"input": "2.50", "input_ceiling": "2.50", "output": "15", "valid_through": None},
    "gpt-5.5-2026-04-23": {"input": "5", "input_ceiling": "5", "output": "30", "valid_through": None},
    "gpt-6-astra": {"input": "10", "input_ceiling": "25", "output": "50", "valid_through": None},
    "claude-opus-4-5-20251101": {"input": "5", "input_ceiling": "10", "output": "25", "valid_through": None},
    "claude-opus-4-6": {"input": "5", "input_ceiling": "10", "output": "25", "valid_through": None},
    "claude-fable-5-1": {"input": "10", "input_ceiling": "20", "output": "50", "valid_through": None},
    "gemini-3-flash-preview": {"input": "0.50", "input_ceiling": "0.50", "output": "3", "valid_through": None},
    "gemini-3.6-flash": {"input": "0.75", "input_ceiling": "0.75", "output": "3.75", "valid_through": "2026-12-31"},
    "gemini-4-argon": {"input": "2", "input_ceiling": "2", "output": "10", "valid_through": "2026-11-30"},
    "kimi-k3": {"input": "3.00", "input_ceiling": "6.00", "output": "15.00", "valid_through": None},
}
PRICES_RETRIEVED_UTC = "2026-10-29"
PRICES_SOURCE = {
    "gpt-5.2-2025-12-11": ["https://developers.openai.com/api/docs/models/gpt-5.2"],
    "gpt-5.4-2026-03-05": ["https://developers.openai.com/api/docs/models/gpt-5.4"],
    "gpt-5.5-2026-04-23": ["https://developers.openai.com/api/docs/models/gpt-5.5"],
    "gpt-6-astra": ["https://developers.openai.com/api/docs/pricing", "https://developers.openai.com/api/docs/models/gpt-6-astra"],
    "claude-opus-4-5-20251101": ["https://platform.claude.com/docs/en/about-claude/pricing"],
    "claude-opus-4-6": ["https://platform.claude.com/docs/en/about-claude/pricing"],
    "claude-fable-5-1": ["https://platform.claude.com/docs/en/about-claude/pricing", "https://platform.claude.com/docs/en/models/fable-5-1/overview"],
    "gemini-3-flash-preview": ["https://ai.google.dev/gemini-api/docs/pricing"],
    "gemini-3.6-flash": ["https://ai.google.dev/gemini-api/docs/pricing"],
    "gemini-4-argon": ["https://ai.google.dev/gemini-api/docs/pricing", "https://ai.google.dev/gemini-api/docs/latest-model"],
    "kimi-k3": ["https://platform.kimi.ai/docs/pricing/chat", "https://platform.kimi.ai/docs/guide/context-caching"],
}
SETTINGS_SOURCE = {
    "openai": ["https://developers.openai.com/api/docs/models/gpt-5.2", "https://developers.openai.com/api/docs/models/gpt-5.4",
               "https://developers.openai.com/api/docs/models/gpt-5.5", "https://developers.openai.com/api/docs/models/gpt-6-astra",
               "https://developers.openai.com/api/docs/guides/latest-model"],
    "anthropic": ["https://platform.claude.com/docs/en/models/fable-5-1/overview",
                  "https://platform.claude.com/docs/en/about-claude/models/choosing-a-model",
                  "https://platform.claude.com/docs/en/build-with-claude/thinking"],
    "google": ["https://ai.google.dev/gemini-api/docs/models/gemini-4-argon", "https://ai.google.dev/gemini-api/docs/latest-model",
               "https://ai.google.dev/gemini-api/docs/generate-content/long-decode", "https://ai.google.dev/gemini-api/docs/thinking",
               "https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.5",
               "https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.6",
               "https://ai.google.dev/gemini-api/docs/deprecations"],
    "moonshot": ["https://platform.kimi.ai/docs/guide/kimi-k3-quickstart"],
}
EXCLUDED_IDENTIFIERS = {"gemini-3.5-flash": "deprecated; requests are automatically routed to gemini-3.6-flash",
                        "gpt-4-0613": "PA1 qualifying model; not scheduled"}

HISTORICAL_PILOTS = {
    "gemini-3-flash-preview": {
        "repository": "https://github.com/theonlypal/gemini3-crossscript-prerequisite-replication",
        "commit": "65bb67b9b535282345e0f73bae95bcee55f2ed5c", "run": "runs/pilot-20261012-paid",
        "settings": "generateContent, maxOutputTokens 8192, thinkingLevel MINIMAL, includeThoughts false, candidateCount 1, temperature omitted",
        "returned_model": "gemini-3-flash-preview",
        "observed": "40 of 40 HTTP 200 with finishReason STOP; 0 Voids; 40 nonempty; pilot-0009 exact T1 (U+0634 U+05B8 U+05C1 U+05E8 U+05B0 U+05D8) under the rule-removed system with input SHART",
    },
    "gemini-3.6-flash": {
        "repository": "https://github.com/theonlypal/gemini36-crossscript-prerequisite-replication",
        "commit": "4c91342383d42dc8eb453b84ef7ca73c99633142", "run": "runs/pilot-20261012-paid",
        "settings": "generateContent, maxOutputTokens 8192, thinkingLevel MINIMAL, includeThoughts false, candidateCount 1, temperature omitted",
        "returned_model": "gemini-3.6-flash",
        "observed": "40 of 40 HTTP 200 with finishReason STOP; 12 V2, 28 nonempty; V2 in 12 of 15 mismatching, 0 of 15 matching and 0 of 10 rule-removed trials; pilot-0037 (cell E, RULE_C with SHART) U+0634 U+05B7 U+05C1 U+05E8 U+05B0 U+05D8 with patah, not T1",
    },
}

STUDIES = ("A", "B")
EXPERIMENT_OF = {"A": 2, "B": 3}

STUDY_A_SYSTEM = "You are the concept the user names. Embody it completely. Output only what the concept itself would say or express."
STUDY_A_INPUTS = ["Be silence.", "Be nothing.", "Be the null.", "Say hello.", "Be a cat.", "Be speech.", "Be something.", "Be a value."]
STUDY_A_NULL_INPUTS = STUDY_A_INPUTS[:3]
STUDY_A_CONTROL_INPUTS = STUDY_A_INPUTS[3:]
STUDY_A_MAX_TOKENS = 4000

RULE_C = "You are שָׁרְט the user names. Embody it completely. Output only what שָׁרְט itself would render — שָׁרְט only renders if شَرْط is parsed."
RULE_S = "You are שָׁרְט the user names. Embody it completely. Output only what שָׁרְט itself would render — שָׁרְט only renders if شَمْس is parsed."
SHART = "شَرْط"
SHAMS = "شَمْس"
STUDY_B_CELLS = {"E": ("RULE_C", "SHART"), "F": ("RULE_C", "SHAMS"), "G": ("RULE_S", "SHART"), "H": ("RULE_S", "SHAMS")}
STUDY_B_STRINGS = {"RULE_C": RULE_C, "RULE_S": RULE_S, "SHART": SHART, "SHAMS": SHAMS}
STUDY_B_MAX_TOKENS = 16000
EXACT_TARGETS = {"T1": "شָׁרְט", "T0": "شָרְט", "HE": "שָׁרְט", "SHART": SHART, "SHAMS": SHAMS}

PREFLIGHT_SYSTEM = "You are a helpful assistant."
PREFLIGHT_INPUT = "Hello"
PREFLIGHT_CHECKS = ("A-t0", "A-omit", "B")


def preflight_checks(model):
    return PREFLIGHT_CHECKS if MODEL_CONFIG[model]["temperature"] == "probe" else ("A-omit", "B")

PA1_QUALIFYING = {"claude-opus-4-6": {"voids": 330, "trials": 330}, "gpt-4-0613": {"voids": 327, "trials": 330},
                  "gpt-5.2-2025-12-11": {"voids": 312, "trials": 330}, "gpt-5.5-2026-04-23": {"voids": 316, "trials": 330}}

VARIANTS = {"t0": 0, "omit": None}
SEEDS = {"A": "VOID-MARK-A-NULL-EMBODIMENT-20261028-v1", "B": "VOID-MARK-B-PREREQUISITE-20261028-v1",
         "preflight": "VOID-MARK-PREFLIGHT-20261028-v1"}
REPLICATES = {"A": 30, "B": 50}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def pretty(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def usd(nano_usd):
    return nano_usd / 1_000_000_000


def milli_price(model, kind):
    """Price in thousandths of a USD per million tokens, so token counts times price are nano-USD integers."""
    price = Decimal(PRICES_USD_PER_MTOK[model][kind]) * 1000
    assert price >= 0
    assert price == price.to_integral_value(), "Price finer than 0.001 USD per million tokens"
    return int(price)


def reservation_nano_usd(model, max_tokens):
    return max_tokens * milli_price(model, "output") + RESERVED_INPUT_TOKENS * milli_price(model, "input_ceiling")


def usage_nano_usd(model, usage):
    def count(key):
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    if not isinstance(usage, dict) or count("input_tokens") is None or count("output_tokens") is None:
        return None
    inputs = sum(count(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return inputs * milli_price(model, "input_ceiling") + count("output_tokens") * milli_price(model, "output")


def price_current(model, today):
    """False once the UTC date passes the documented end of a rate."""
    through = PRICES_USD_PER_MTOK[model]["valid_through"]
    return through is None or today <= through


def slot_strings(study, slot):
    if study == "A":
        return STUDY_A_SYSTEM, slot["input"], STUDY_A_MAX_TOKENS
    if study == "B":
        rule, user = STUDY_B_CELLS[slot["cell"]]
        return STUDY_B_STRINGS[rule], STUDY_B_STRINGS[user], STUDY_B_MAX_TOKENS
    raise ValueError(study)


def study_variants(study, model):
    return ("t0", "omit") if study == "A" and MODEL_CONFIG[model]["temperature"] == "probe" else ("omit",)


def build(vendor, model, system, user, max_tokens, temperature):
    return vendors.build_request(vendor, model, system, user, max_tokens, temperature, MODEL_CONFIG[model]["reasoning"])


def request(study, slot, variant):
    """Endpoint URL and body for one scheduled slot under one temperature variant."""
    assert variant in study_variants(study, slot["model"]), "Variant not allowed for " + slot["slot_id"]
    system, user, max_tokens = slot_strings(study, slot)
    return build(slot["vendor"], slot["model"], system, user, max_tokens, VARIANTS[variant])


def request_bytes(study, slot, variant):
    return canonical(request(study, slot, variant)[1])


def max_tokens_of(study):
    return STUDY_A_MAX_TOKENS if study == "A" else STUDY_B_MAX_TOKENS


def preflight_request(check, vendor, model):
    assert check in preflight_checks(model), "Check not scheduled for " + model
    if check in ("A-t0", "A-omit"):
        return build(vendor, model, PREFLIGHT_SYSTEM, PREFLIGHT_INPUT, STUDY_A_MAX_TOKENS, VARIANTS[check[2:]])
    return build(vendor, model, PREFLIGHT_SYSTEM, PREFLIGHT_INPUT, STUDY_B_MAX_TOKENS, None)


def conditions(study, vendor):
    if study == "A":
        return [{"vendor": vendor, "model": m, "input": p} for m in MODELS[vendor] for p in STUDY_A_INPUTS]
    if study == "B":
        return [{"vendor": vendor, "model": m, "cell": c} for m in MODELS[vendor] for c in STUDY_B_CELLS]
    raise ValueError(study)


def build_schedule(study, vendor):
    rows = [dict(c, replicate=r) for c in conditions(study, vendor) for r in range(1, REPLICATES[study] + 1)]
    random.Random(f"{SEEDS[study]}-{vendor}").shuffle(rows)
    schedule = []
    for i, row in enumerate(rows, 1):
        slot = dict(slot_id=f"{study}-{vendor}-{i:05d}", **row)
        slot["request_sha256"] = {v: digest(request_bytes(study, slot, v)) for v in study_variants(study, slot["model"])}
        schedule.append(slot)
    return schedule


def build_preflight_schedule():
    schedule = []
    for vendor in VENDORS:
        for model in MODELS[vendor]:
            for check in preflight_checks(model):
                slot = {"slot_id": f"preflight-{model}-{check}", "vendor": vendor, "model": model, "check": check}
                slot["request_sha256"] = {"omit": digest(canonical(preflight_request(check, vendor, model)[1]))}
                schedule.append(slot)
    return schedule


DOI_LINE = re.compile(r"DOI: https://doi\.org/10\.5281/zenodo\.[0-9]+")


def prereg_canonical(data):
    """PREREG.md bytes without the one permitted DOI line; every other byte is bound."""
    lines = data.decode("utf-8").split("\n")
    kept = [line for line in lines if not DOI_LINE.fullmatch(line)]
    assert len(lines) - len(kept) <= 1, "More than one DOI line in PREREG.md"
    return "\n".join(kept).encode("utf-8")


def schedule_name(study, vendor):
    return f"{study}-{vendor}.json"


def schedule_path(study, vendor):
    return ROOT / "schedules" / schedule_name(study, vendor)


def load_schedule(study):
    """Every vendor schedule of one study, each verified against protocol.json and regenerated from its seed."""
    protocol = json.loads((ROOT / "protocol.json").read_bytes())
    if study == "preflight":
        raw = (ROOT / "schedules" / "preflight.json").read_bytes()
        assert digest(raw) == protocol["preflight"]["schedule_sha256"], "Schedule hash mismatch"
        schedule = json.loads(raw)
        assert schedule == build_preflight_schedule(), "Preflight schedule does not regenerate"
        return schedule
    schedule = []
    for vendor in VENDORS:
        raw = schedule_path(study, vendor).read_bytes()
        assert digest(raw) == protocol["studies"][study]["schedules"][vendor]["sha256"], "Schedule hash mismatch"
        part = json.loads(raw)
        assert part == build_schedule(study, vendor), "Schedule does not regenerate from seed"
        schedule.extend(part)
    return schedule
