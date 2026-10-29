"""Generate the frozen protocol, prompts, Unicode manifest and schedules. Refuses to overwrite."""
from frozen import (ROOT, TITLE, AUTHOR, FROZEN_TAG, VENDORS, MODELS, VENDOR_OF, MODEL_CONFIG, PINNED, STUDIES,
                    EXPERIMENT_OF, SEEDS, REPLICATES, CONCURRENCY_PER_VENDOR, CREDENTIAL_ENV, STUDY_A_SYSTEM, STUDY_A_INPUTS,
                    STUDY_A_NULL_INPUTS, STUDY_A_CONTROL_INPUTS, STUDY_A_MAX_TOKENS, STUDY_B_CELLS, STUDY_B_STRINGS,
                    STUDY_B_MAX_TOKENS, EXACT_TARGETS, PREFLIGHT_SYSTEM, PREFLIGHT_INPUT, MAX_SPEND_USD, PRICES_USD_PER_MTOK,
                    PRICES_SOURCE, PRICES_RETRIEVED_UTC, SETTINGS_SOURCE, EXCLUDED_IDENTIFIERS, HISTORICAL_PILOTS,
                    RESERVED_INPUT_TOKENS, PA1_QUALIFYING, VARIANTS, build, conditions, build_schedule,
                    build_preflight_schedule, preflight_checks, schedule_name, schedule_path, digest,
                    pretty, prereg_canonical, study_variants, usd)
import analysis
import classifier
import qualifying
import runner
import vendors
import verify
import xclassify


def prompts():
    return {
        "study_a": {"system": STUDY_A_SYSTEM, "inputs": STUDY_A_INPUTS, "null_inputs": STUDY_A_NULL_INPUTS,
                    "control_inputs": STUDY_A_CONTROL_INPUTS},
        "study_b": {"strings": STUDY_B_STRINGS, "cells": {c: {"system": r, "input": u} for c, (r, u) in STUDY_B_CELLS.items()}},
        "exact_targets": EXACT_TARGETS,
        "preflight": {"system": PREFLIGHT_SYSTEM, "input": PREFLIGHT_INPUT},
    }


def unicode_manifest():
    strings = {"study_a.system": STUDY_A_SYSTEM}
    for i, p in enumerate(STUDY_A_INPUTS, 1):
        strings[f"study_a.input.{i}"] = p
    for k, v in STUDY_B_STRINGS.items():
        strings["study_b." + k] = v
    for k, v in EXACT_TARGETS.items():
        strings["target." + k] = v
    strings["preflight.system"] = PREFLIGHT_SYSTEM
    strings["preflight.input"] = PREFLIGHT_INPUT
    return {k: {"literal": v, "codepoints": [f"U+{ord(c):04X}" for c in v], "utf8_hex": v.encode().hex(),
                "byte_length": len(v.encode()), "sha256": digest(v.encode())} for k, v in strings.items()}


def cost_envelope():
    """Sum of per-request reservations over every scheduled request, by model, from the frozen prices."""
    rows = {}
    for vendor in VENDORS:
        for model in MODELS[vendor]:
            row = {"vendor": vendor}
            for study in STUDIES:
                slots = [s for s in build_schedule(study, vendor) if s["model"] == model]
                row[study] = {"requests": len(slots), "nano_usd": sum(verify.reservation(study, s) for s in slots)}
            pre = [s for s in build_preflight_schedule() if s["model"] == model]
            row["preflight"] = {"requests": len(pre), "nano_usd": sum(verify.reservation("preflight", s) for s in pre)}
            row["total_nano_usd"] = sum(row[k]["nano_usd"] for k in ("A", "B", "preflight"))
            rows[model] = row
    total = sum(r["total_nano_usd"] for r in rows.values())
    return {"models": {m: {"vendor": r["vendor"], **{k: {"requests": r[k]["requests"], "usd": usd(r[k]["nano_usd"])}
                                                     for k in ("A", "B", "preflight")}, "total_usd": usd(r["total_nano_usd"])}
                       for m, r in rows.items()},
            "total_usd": usd(total), "max_spend_usd": MAX_SPEND_USD, "fits_within_cap": total <= MAX_SPEND_USD * 1_000_000_000}


def money(value):
    return f"{value:,.4f}"


def cost_table():
    """Markdown table reproduced verbatim in PREREG.md."""
    env = cost_envelope()
    lines = ["| Model | Study A requests | Study A (USD) | Study B requests | Study B (USD) | Preflight requests | Preflight (USD) | Total (USD) |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for model, r in env["models"].items():
        lines.append(f"| `{model}` | {r['A']['requests']:,} | {money(r['A']['usd'])} | {r['B']['requests']:,} | {money(r['B']['usd'])} "
                     f"| {r['preflight']['requests']} | {money(r['preflight']['usd'])} | {money(r['total_usd'])} |")
    totals = {k: sum(r[k]["requests"] for r in env["models"].values()) for k in ("A", "B", "preflight")}
    sums = {k: sum(r[k]["usd"] for r in env["models"].values()) for k in ("A", "B", "preflight")}
    lines.append(f"| Total | {totals['A']:,} | {money(sums['A'])} | {totals['B']:,} | {money(sums['B'])} | {totals['preflight']} "
                 f"| {money(sums['preflight'])} | {money(env['total_usd'])} |")
    return "\n".join(lines) + "\n"


def model_table():
    """Markdown table reproduced verbatim in PREREG.md."""
    lines = ["| Vendor | Model | Identifier | Reasoning setting | Study A temperature | Price input / input ceiling / output (USD per MTok) |",
             "|---|---|---|---|---|---|"]
    for model, cfg in MODEL_CONFIG.items():
        p = PRICES_USD_PER_MTOK[model]
        temperature = "0 if accepted at preflight, else omitted" if cfg["temperature"] == "probe" else "omitted"
        through = f" (through {p['valid_through']})" if p["valid_through"] else ""
        lines.append(f"| {VENDOR_OF[model]} | `{model}` | {cfg['identifier']} | {cfg['reasoning_note']} | {temperature} "
                     f"| {p['input']} / {p['input_ceiling']} / {p['output']}{through} |")
    return "\n".join(lines) + "\n"


def mapping():
    rows = {}
    for vendor in VENDORS:
        rows[vendor] = {"fields": vendors.FIELDS[vendor],
                        "stop_reason": "unchanged" if vendor == "anthropic" else vendors.STOP_MAP[vendor],
                        "unmapped_stop": "passed through unchanged"}
    return {"vendors": rows, "signals": vendors.SIGNALS,
            "gemini_safety_stops": sorted(vendors.GEMINI_SAFETY_STOPS), "gemini_tool_stops": sorted(vendors.GEMINI_TOOL_STOPS),
            "chat_safety_stops": sorted(vendors.CHAT_SAFETY_STOPS), "chat_tool_stops": sorted(vendors.CHAT_TOOL_STOPS),
            "anthropic_block_types": sorted(vendors.ANTHROPIC_BLOCK_TYPES)}


def request_templates():
    out = {}
    for model, cfg in MODEL_CONFIG.items():
        vendor = VENDOR_OF[model]
        url, body = build(vendor, model, "<system>", "<input>", "<max_tokens>", "<temperature>" if cfg["temperature"] == "probe" else None)
        out[model] = {"url": url, "body": body, "study_a_variants": list(study_variants("A", model)),
                      "study_b_variants": list(study_variants("B", model)), "preflight_checks": list(preflight_checks(model))}
    return out


def protocol():
    studies = {}
    for study in STUDIES:
        studies[study] = {
            "experiment_classes": EXPERIMENT_OF[study], "seed": SEEDS[study], "replicates_per_condition": REPLICATES[study],
            "max_tokens": STUDY_A_MAX_TOKENS if study == "A" else STUDY_B_MAX_TOKENS,
            "temperature": "per model: 0 where the preflight A-t0 check passes, otherwise omitted; omitted for models whose provider documents temperature as rejected, ignored or fixed" if study == "A" else "omitted",
            "classes": xclassify.CLASSES[EXPERIMENT_OF[study]],
            "upstream_classification_priority": classifier.PRIORITY[EXPERIMENT_OF[study]],
            "schedules": {v: {"path": "schedules/" + schedule_name(study, v), "sha256": digest(schedule_path(study, v).read_bytes()),
                              "requests": len(conditions(study, v)) * REPLICATES[study]} for v in VENDORS},
        }
        studies[study]["requests"] = sum(r["requests"] for r in studies[study]["schedules"].values())
    studies["A"].update(system="prompts.json study_a.system", inputs="prompts.json study_a.inputs")
    studies["B"].update(cells={c: [r, u] for c, (r, u) in STUDY_B_CELLS.items()})
    preflight = build_preflight_schedule()
    return {
        "title": TITLE,
        "author": AUTHOR,
        "frozen_tag": FROZEN_TAG,
        "prereg": {"path": "PREREG.md", "canonical_sha256": digest(prereg_canonical((ROOT / "PREREG.md").read_bytes())),
                   "canonicalization": "UTF-8 text split on LF; at most one line fully matching " + "DOI: https://doi\\.org/10\\.5281/zenodo\\.[0-9]+"
                                       + " is removed; remaining lines joined with LF; SHA-256 of the result"},
        "panel": "fixed selected panel; no dynamic discovery or substitution",
        "vendors": {v: {"endpoint": vendors.ENDPOINTS[v], "models": MODELS[v], "credential_env": CREDENTIAL_ENV[v],
                        "settings_sources": SETTINGS_SOURCE[v], "read_timeout_seconds": vendors.READ_TIMEOUT_SECONDS[v]}
                    for v in VENDORS},
        "models": {m: {"vendor": VENDOR_OF[m], **cfg, "price_usd_per_mtok": PRICES_USD_PER_MTOK[m], "price_sources": PRICES_SOURCE[m]}
                   for m, cfg in MODEL_CONFIG.items()},
        "excluded_identifiers": EXCLUDED_IDENTIFIERS,
        "historical_pilots": HISTORICAL_PILOTS,
        "comparability": "provider-default or provider-required thinking and temperature policies differ across models; this is not an equal-compute or equal-reasoning comparison",
        "request_headers": {"anthropic": {"x-api-key": "<credential>", "anthropic-version": vendors.ANTHROPIC_VERSION},
                            "openai": {"authorization": "Bearer <credential>"}, "moonshot": {"authorization": "Bearer <credential>"},
                            "google": {"x-goog-api-key": "<credential>"}, "all": {"content-type": "application/json"}},
        "request_templates": request_templates(),
        "temperature_variants": {k: ("omitted" if v is None else v) for k, v in VARIANTS.items()},
        "omitted_fields": "stream, top_p, top_k, seed, stop sequences, tools, tool_choice, metadata, response_format, candidateCount, includeThoughts, safety settings, continuationToken, cache options; Anthropic thinking and effort; Moonshot reasoning_effort",
        "single_request": "one HTTP request per attempt; no streaming, automatic continuation, SDK retry, background execution or follow-up request",
        "request_serialization": "UTF-8 JSON, ensure_ascii=False, sort_keys=True, separators comma/colon",
        "fresh_context": "exactly one user message per request; system instruction where specified",
        "concurrency_per_vendor": CONCURRENCY_PER_VENDOR,
        "dispatch": "one queue per vendor in schedule order; concurrency_per_vendor workers per vendor; vendors in parallel; each slot's attempts and retries stay on one worker; events appended to one hash chain per output folder under one lock",
        "schedule_algorithm": "rows = conditions x replicates in frozen order; Python random.Random(seed + '-' + vendor).shuffle(rows); saved schedule is authoritative",
        "studies": studies,
        "requests_total": sum(studies[s]["requests"] for s in STUDIES),
        "preflight": {"input": PREFLIGHT_INPUT, "system": PREFLIGHT_SYSTEM,
                      "checks": {"A-t0": "Study A shape, max_tokens 4000, temperature 0 (temperature probe models only)",
                                 "A-omit": "Study A shape, max_tokens 4000, temperature omitted",
                                 "B": "Study B shape, max_tokens 16000, temperature omitted"},
                      "schedule": "schedules/preflight.json", "schedule_sha256": digest((ROOT / "schedules" / "preflight.json").read_bytes()),
                      "requests": len(preflight),
                      "check_pass": "HTTP 200, model completion, returned model equals requested model, nonempty response id",
                      "attempts": "one attempt per check; interrupted and QE attempts do not count and are re-dispatched on resume; other failures are not retried",
                      "model_status": "PASS when B passes and A-t0 or A-omit passes; otherwise OP",
                      "study_a_variant": "t0 when A-t0 passes, otherwise omit",
                      "op": "every slot of an OP model is recorded OP in both studies with its preflight checks; no request is sent",
                      "required_before_run": "complete frozen preflight on the same commit",
                      "status_at_freeze": "UNEXECUTED"},
        "identity": "returned model (OpenAI and Moonshot model, Anthropic model, Google modelVersion) must equal the requested identifier; no allowlist of alternative returned identifiers; a mismatch fails the preflight check or ends the study as INCONCLUSIVE",
        "retry": {"max_attempts": runner.MAX_ATTEMPTS, "backoff_seconds": runner.BACKOFF_SECONDS,
                  "eligible": ["any httpx.TransportError, including client read timeouts", "HTTP 429 not QE", "HTTP 5xx"],
                  "wait": f"HTTP 429 or 5xx with a retry-after header: min(ceil(value), {runner.RETRY_AFTER_MAX_SECONDS}) seconds; otherwise backoff_seconds",
                  "interrupted_and_QE_attempts": "not counted toward max_attempts",
                  "completed_responses": "never retried",
                  "timeouts": "client or server timeouts are operational failures (class E), never Voids"},
        "spend": {"max_spend_usd": MAX_SPEND_USD,
                  "scope": "one cap over preflight, study A and study B together, cumulative across resumes, with per-vendor subtotals",
                  "prices_usd_per_mtok": PRICES_USD_PER_MTOK, "prices_retrieved_utc": PRICES_RETRIEVED_UTC,
                  "price_expiry": "a model whose rate is past valid_through (UTC date) is not dispatched: the run refuses to start or pauses with reason price expired; continuing requires a new pricing check and a new frozen protocol",
                  "reservation": f"max_tokens x output price + {RESERVED_INPUT_TOKENS} x input_ceiling, before each dispatch",
                  "cap_rule": "if other folders' spend + this folder's spend + in-flight reservations + reservation > max_spend_usd: PAUSED, reason spend cap, no dispatch",
                  "settlement": {"2xx with usage": "reservation replaced by usage cost",
                                 "2xx without usage, transport error, interrupt, abandoned attempt": "reservation kept as spent; never released",
                                 "non-2xx HTTP response": "0"},
                  "usage_cost": "mapped (input_tokens + cache_creation_input_tokens + cache_read_input_tokens) x input_ceiling + mapped output_tokens x output price; output_tokens include thinking tokens",
                  "ledger_status": "an estimate from reported usage and frozen prices, not a provider invoice",
                  "cost_envelope_usd": cost_envelope(),
                  "cost_envelope_basis": "sum of reservations over every scheduled study and preflight request; the cap is a maximum, not a completion guarantee"},
        "statuses": {"COMPLETE": "every scheduled slot has exactly one definitive record (model completion or OP)",
                     "PAUSED": "spend cap, price expired, provider quota (QE) or interrupted; resumable", "INCONCLUSIVE": "terminal"},
        "resume": "replay and verify the event chain, skip slots with a definitive record, append to events.jsonl, never write into an existing attempt folder; requires the commit, freeze mode and environment of the original run",
        "run_commit": f"HEAD equals the {FROZEN_TAG} commit, or descends from it with a diff of exactly one added line in PREREG.md and an unchanged PREREG.md canonical hash",
        "timeouts": {v: {"connect": 30, "read": vendors.READ_TIMEOUT_SECONDS[v], "write": 30, "pool": 30} for v in VENDORS},
        "stop_rules": {"returned_model_differs": "INCONCLUSIVE", "no_definitive_completion": "INCONCLUSIVE",
                       "frozen_integrity_failure": "INCONCLUSIVE", "spend_cap": "PAUSED", "price_expired": "PAUSED",
                       "provider_quota_QE": "PAUSED", "interrupted": "PAUSED",
                       "existing_output": "resume if not COMPLETE or INCONCLUSIVE; otherwise refuse"},
        "persisted_response_headers": sorted(runner.RESPONSE_HEADERS),
        "persisted_attempt_files": ["request.bin", "response.bin (vendor bytes, unaltered)", "classifier_input.bin (extractor output)",
                                    "attempt.json", "classification.json"],
        "extractors": mapping(),
        "classification": {"version": xclassify.VERSION, "entrypoint": "xclassify.classify_attempt",
                            "upstream": {"file": "classifier.py", "sha256": digest((ROOT / "classifier.py").read_bytes()),
                                         "source": "https://github.com/theonlypal/opus45-opus46-matched-prereg-final tag v1.0.0"},
                            "extension": xclassify.__doc__.strip(), "rules": xclassify.RULES,
                            "extension_classes": xclassify.EXTENSION_CLASSES},
        "taxonomy": {
            "void": classifier.VOID_TAXONOMY,
            "void_status": classifier.VOID_STATUS,
            "non_void": dict(classifier.NON_VOID_TAXONOMY, **xclassify.EXTENSION_CLASSES),
            "cross_script": classifier.CROSS_SCRIPT_TAXONOMY,
            "void_classes": classifier.VOID_CLASSES,
            "op": "Preflight exclusion; no request sent in the study",
            "visible_text": "concatenation of all text blocks in response order after extraction; absent text blocks yield an absent text container",
            "normal_stops": classifier.NORMAL_STOPS,
            "budget_stops": classifier.BUDGET_STOPS,
            "invisible_codepoints": [f"U+{c:04X}" for c in classifier.INVISIBLE_CODEPOINTS],
            "ellipsis_forms": classifier.ELLIPSIS_FORMS,
            "http_errors": {"BE": {"statuses": [400, 413, 422], "markers": classifier.BUDGET_MARKERS},
                            "QE": {"statuses": [400, 402, 429], "markers": classifier.QUOTA_MARKERS},
                            "PI": {"statuses": [400, 404, 405, 413, 422]},
                            "E": "all other non-2xx statuses, transport failures and malformed successful responses"},
            "study_b_descriptors": "contains (substring presence of each exact target), mixed_script_words (letter-and-mark runs containing both Script=Arabic and Script=Hebrew)",
            "normalization": "none; whitespace and invisible code points are nonempty; Unicode variants are distinct",
        },
        "analysis": analysis.RULES,
        "pa1_qualifying": {"source": qualifying.SOURCE, "rule": qualifying.__doc__.split("\n\n")[1].replace("\n", " ").strip(),
                           "threshold": qualifying.THRESHOLD, "models": PA1_QUALIFYING},
        "dependencies": PINNED,
        "event_hash": "SHA256 of canonical UTF-8 JSON excluding event_hash; first prev_hash 64 zeroes",
    }


def write(name, data):
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(data)


def main():
    write("prompts.json", pretty(prompts()))
    write("unicode_manifest.json", pretty(unicode_manifest()))
    for study in STUDIES:
        for vendor in VENDORS:
            write("schedules/" + schedule_name(study, vendor), pretty(build_schedule(study, vendor)))
    write("schedules/preflight.json", pretty(build_preflight_schedule()))
    write("protocol.json", pretty(protocol()))


if __name__ == "__main__":
    main()
