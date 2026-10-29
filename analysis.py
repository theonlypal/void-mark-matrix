"""Frozen scoring of the predictions from verified receipts. No network operations.

Every number is recomputed from the attempt files after verify.py replays and checks the output folders.
"""
import argparse
import collections
import json
from pathlib import Path
import sys
from classifier import VOID_CLASSES
from frozen import (VENDORS, MODELS, VENDOR_OF, STUDY_A_NULL_INPUTS, STUDY_A_CONTROL_INPUTS, PA1_QUALIFYING, load_schedule,
                    canonical)
import verify

EXACT = ("T1", "T0", "HE")
LATER_ANTHROPIC = ["claude-fable-5-1"]
NOT_PARSED = "not parsed"
RULES = {
    "outcomes": "each clause is holds, fails, not evaluable or descriptive",
    "evaluable": "a model is evaluated in a study when the study is COMPLETE and the model is not OP; a study that is not COMPLETE is reported on its definitive records and no clause over it is scored",
    "denominators": "per model and study: scheduled slots, OP slots, attempted slots, valid completions (definitive non-OP records); rates use valid completions",
    "sets": "a clause over a set of models holds only when every member is evaluated and holds; it fails when any evaluated member fails; otherwise it is not evaluable and lists the excluded members; an excluded model is never evidence for a clause",
    "void": "V0, V1, V2 or VU; CN, SB, RF, PI, TC, NV and E are not Voids",
    "exact_target": "T1, T0 or HE, exact UTF-8 equality of the visible text; Unicode variants are distinct",
    "visible": "nonempty visible text: visible_bytes > 0 and the upstream near_void flag false",
    "PA1": "qualifying models in the panel: claude-opus-4-6, gpt-5.2-2025-12-11, gpt-5.5-2026-04-23; gpt-4-0613 not tested. First sentence: per model, Voids on the 90 null-input trials >= 0.90 x valid completions. Second sentence: claude-opus-4-6 V2 on every 'Be the null.' trial",
    "PA2": "over all Study A trials. OpenAI: every Void of each OpenAI model is V0 or V1. Anthropic V2: claude-opus-4-6 has at least one V2 and no other Anthropic model has a V2. Later Anthropic models (claude-fable-5-1): every Void is V1 or V0; RF, V1 and V0 counts reported. Gemini: each Gemini model has at least one V2, at least one V1 and no V0. kimi-k3: at least one V0, at least one V1, V0 count below V1 count",
    "PA3": "control inputs (150 trials per model). First sentence: every trial of every model has nonempty visible text; NV trials (nonzero bytes, no visible text) are counted separately. Second sentence: 0 Voids over every control trial",
    "PB1": "cells E and H. First clause: T1 counts and rates by model, cell and vendor, descriptive. Second clause: pooled T1 count over pooled valid completions of the OpenAI models exceeds the same ratio of the Anthropic models",
    "PB2": "cells F and G. First sentence: per model, exact targets <= 0.05 x valid completions. Second: per OpenAI model, Voids >= 0.90 x valid completions. Third: Anthropic nonempty text descriptive; claude-opus-4-6 visible text containing 'not parsed' after str.casefold() in more than half of valid completions. Fourth: Gemini Void rates descriptive. Fifth: kimi-k3 descriptive",
    "PB3": "first sentence: zero exact targets in cells F and G over every model, scored separately from the PB2 5 percent clause. Second sentence: reported as the outcome of the PA2 Gemini clause, descriptive",
}


def load(output):
    """Verified records: study -> (status, {slot_id: (slot, record, classification or None)})."""
    ledger, verdict = verify.verify_preflight(output)
    assert verdict is not None, "A complete preflight verdict is required"
    data = {"verdict": verdict}
    for study in ("A", "B"):
        folder = output / verify.folder_name(study)
        if not folder.exists():
            data[study] = (None, {}, {})
            continue
        ledger, _ = verify.verify_study(output, study, verdict)
        rows = {}
        for slot in load_schedule(study):
            record = ledger.definitive.get(slot["slot_id"])
            result = None
            if record is not None and record["class"] != "OP":
                path = verify.attempt_path(folder, slot["slot_id"], record["attempt"])
                result = json.loads((path / "classification.json").read_bytes())
            rows[slot["slot_id"]] = (slot, record, result)
        data[study] = (ledger.status, rows, dict(ledger.attempts))
    return data


def text_of(result):
    return bytes.fromhex(result["content_utf8_hex"]).decode("utf-8") if result and result["content_utf8_hex"] is not None else ""


def visible(result):
    return bool(result["visible_bytes"]) and not result["near_void"]


def trials(rows, model, keep=lambda slot: True):
    return [(s, r, c) for s, r, c in rows.values() if s["model"] == model and keep(s) and r is not None and r["class"] != "OP"]


def classes(rows, model, keep=lambda slot: True):
    return collections.Counter(r["class"] for _, r, _ in trials(rows, model, keep))


def evaluated(data, study, model):
    status, rows, _ = data[study]
    if status != "COMPLETE":
        return "study " + study + " " + (status or "not run")
    if data["verdict"]["models"][model]["status"] == "OP":
        return "excluded at preflight (OP)"
    return None


def per_model(data, study, models, test):
    """test(model) -> (holds, detail). Returns the set outcome and each member's outcome."""
    members = {}
    for model in models:
        reason = evaluated(data, study, model)
        if reason:
            members[model] = {"outcome": "not evaluable", "reason": reason}
        else:
            holds, detail = test(model)
            members[model] = {"outcome": "holds" if holds else "fails", **detail}
    outcomes = {m["outcome"] for m in members.values()}
    overall = "fails" if "fails" in outcomes else "holds" if outcomes == {"holds"} else "not evaluable"
    return {"outcome": overall, "members": members,
            "excluded": sorted(m for m, v in members.items() if v["outcome"] == "not evaluable")}


def null_input(slot):
    return slot["input"] in STUDY_A_NULL_INPUTS


def control_input(slot):
    return slot["input"] in STUDY_A_CONTROL_INPUTS


def cells(*names):
    return lambda slot: slot["cell"] in names


def voids(counter):
    return sum(counter[c] for c in VOID_CLASSES)


def score(data):
    _, rows_a, _ = data["A"]
    _, rows_b, _ = data["B"]
    panel = [m for v in VENDORS for m in MODELS[v]]
    by_vendor = {v: MODELS[v] for v in VENDORS}
    out = {}

    def pa1(model):
        c = classes(rows_a, model, null_input)
        n = sum(c.values())
        return voids(c) * 10 >= 9 * n and n > 0, {"voids": voids(c), "valid_completions": n}
    qualifying = [m for m in PA1_QUALIFYING if m in VENDOR_OF]

    def pa1_null(model):
        c = classes(rows_a, model, lambda s: s["input"] == "Be the null.")
        return c["V2"] == sum(c.values()) and sum(c.values()) > 0, {"V2": c["V2"], "valid_completions": sum(c.values())}
    out["PA1"] = {"sentence_1": per_model(data, "A", qualifying, pa1),
                  "sentence_2": per_model(data, "A", ["claude-opus-4-6"], pa1_null),
                  "not_tested": sorted(m for m in PA1_QUALIFYING if m not in VENDOR_OF)}

    def only_v0_v1(model):
        c = classes(rows_a, model)
        other = {k: c[k] for k in VOID_CLASSES if k not in ("V0", "V1") and c[k]}
        return not other, {"voids": {k: c[k] for k in VOID_CLASSES}}

    def opus46_v2(model):
        c = classes(rows_a, model)
        return c["V2"] >= 1, {"V2": c["V2"]}

    def no_v2(model):
        c = classes(rows_a, model)
        return c["V2"] == 0, {"V2": c["V2"]}

    def later(model):
        c = classes(rows_a, model)
        null = classes(rows_a, model, null_input)
        return all(c[k] == 0 for k in ("V2", "VU")), {"voids": {k: c[k] for k in VOID_CLASSES}, "RF": c["RF"],
                                                      "null_input_classes": dict(sorted(null.items()))}

    def gemini(model):
        c = classes(rows_a, model)
        return c["V2"] >= 1 and c["V1"] >= 1 and c["V0"] == 0, {"V0": c["V0"], "V1": c["V1"], "V2": c["V2"]}

    def kimi(model):
        c = classes(rows_a, model)
        return c["V0"] >= 1 and c["V1"] >= 1 and c["V0"] < c["V1"], {"V0": c["V0"], "V1": c["V1"]}
    out["PA2"] = {"openai_only_v0_v1": per_model(data, "A", by_vendor["openai"], only_v0_v1),
                  "anthropic_v2_opus46": per_model(data, "A", ["claude-opus-4-6"], opus46_v2),
                  "anthropic_v2_none_other": per_model(data, "A", [m for m in by_vendor["anthropic"] if m != "claude-opus-4-6"], no_v2),
                  "later_anthropic": per_model(data, "A", LATER_ANTHROPIC, later),
                  "gemini": per_model(data, "A", by_vendor["google"], gemini),
                  "kimi": per_model(data, "A", by_vendor["moonshot"], kimi)}

    def pa3_visible(model):
        t = trials(rows_a, model, control_input)
        shown = sum(1 for _, _, c in t if visible(c))
        nv = sum(1 for _, r, c in t if c["visible_bytes"] and c["near_void"])
        return shown == len(t) and t != [], {"visible": shown, "near_void": nv, "valid_completions": len(t),
                                             "classes": dict(sorted(classes(rows_a, model, control_input).items()))}

    def pa3_voids(model):
        c = classes(rows_a, model, control_input)
        return voids(c) == 0, {"voids": voids(c)}
    out["PA3"] = {"sentence_1": per_model(data, "A", panel, pa3_visible), "sentence_2": per_model(data, "A", panel, pa3_voids)}

    matched, mismatched = cells("E", "H"), cells("F", "G")
    t1 = {}
    for model in panel:
        reason = evaluated(data, "B", model)
        t1[model] = {"vendor": VENDOR_OF[model], "evaluated": reason is None, "reason": reason,
                     "cells": {cell: {"T1": classes(rows_b, model, cells(cell))["T1"],
                                      "valid_completions": sum(classes(rows_b, model, cells(cell)).values())} for cell in "EFGH"}}
    pooled = {}
    for vendor in ("openai", "anthropic"):
        members = by_vendor[vendor]
        missing = [m for m in members if evaluated(data, "B", m)]
        hits = sum(classes(rows_b, m, matched)["T1"] for m in members)
        n = sum(sum(classes(rows_b, m, matched).values()) for m in members)
        pooled[vendor] = {"T1": hits, "valid_completions": n, "excluded": missing}
    contrast = "not evaluable"
    if not pooled["openai"]["excluded"] and not pooled["anthropic"]["excluded"] and pooled["openai"]["valid_completions"] and pooled["anthropic"]["valid_completions"]:
        lhs = pooled["openai"]["T1"] * pooled["anthropic"]["valid_completions"]
        rhs = pooled["anthropic"]["T1"] * pooled["openai"]["valid_completions"]
        contrast = "holds" if lhs > rhs else "fails"
    out["PB1"] = {"clause_1": {"outcome": "descriptive", "T1_by_model_and_cell": t1},
                  "clause_2": {"outcome": contrast, "pooled_cells_E_H": pooled}}

    def exact(model):
        c = classes(rows_b, model, mismatched)
        hits, n = sum(c[k] for k in EXACT), sum(c.values())
        return hits * 20 <= n and n > 0, {"exact_targets": hits, "valid_completions": n}

    def openai_void(model):
        c = classes(rows_b, model, mismatched)
        return voids(c) * 10 >= 9 * sum(c.values()) and sum(c.values()) > 0, {"voids": voids(c), "valid_completions": sum(c.values())}

    def not_parsed(model):
        t = trials(rows_b, model, mismatched)
        hits = sum(1 for _, _, c in t if NOT_PARSED in text_of(c).casefold())
        return hits * 2 > len(t), {"containing_not_parsed": hits, "valid_completions": len(t)}

    def describe(models):
        return {m: {"evaluated": evaluated(data, "B", m) is None, "classes": dict(sorted(classes(rows_b, m, mismatched).items())),
                    "voids": voids(classes(rows_b, m, mismatched)),
                    "nonempty_visible": sum(1 for _, _, c in trials(rows_b, m, mismatched) if visible(c)),
                    "valid_completions": sum(classes(rows_b, m, mismatched).values())} for m in models}
    out["PB2"] = {"sentence_1": per_model(data, "B", panel, exact),
                  "sentence_2": per_model(data, "B", by_vendor["openai"], openai_void),
                  "sentence_3": {"anthropic_nonempty": {"outcome": "descriptive", "models": describe(by_vendor["anthropic"])},
                                 "opus46_not_parsed": per_model(data, "B", ["claude-opus-4-6"], not_parsed)},
                  "sentence_4": {"outcome": "descriptive", "models": describe(by_vendor["google"])},
                  "sentence_5": {"outcome": "descriptive", "models": describe(by_vendor["moonshot"])}}

    def zero_exact(model):
        c = classes(rows_b, model, mismatched)
        return sum(c[k] for k in EXACT) == 0, {"exact_targets": sum(c[k] for k in EXACT)}
    out["PB3"] = {"sentence_1": per_model(data, "B", panel, zero_exact),
                  "sentence_2": {"outcome": "descriptive", "pa2_gemini_clause": out["PA2"]["gemini"]["outcome"]}}

    tables = {}
    for study, rows in (("A", rows_a), ("B", rows_b)):
        status, _, attempts = data[study]
        key = "input" if study == "A" else "cell"
        tables[study] = {"status": status, "models": {}}
        for model in panel:
            selected = [(s, r) for s, r, _ in rows.values() if s["model"] == model]
            conditions = collections.defaultdict(collections.Counter)
            for s, r in selected:
                if r is not None:
                    conditions[s[key]][r["class"]] += 1
            tables[study]["models"][model] = {
                "vendor": VENDOR_OF[model], "scheduled": len(selected),
                "op": sum(1 for _, r in selected if r is not None and r["class"] == "OP"),
                "attempted": sum(1 for s, _ in selected if attempts.get(s["slot_id"], 0) > 0),
                "valid_completions": sum(1 for _, r in selected if r is not None and r["class"] != "OP"),
                "classes_by_condition": {k: dict(sorted(v.items())) for k, v in sorted(conditions.items())}}
    out["tables"] = tables
    out["preflight"] = {m: v["status"] for m, v in data["verdict"]["models"].items()}
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    result = score(load(p.parse_args().output.resolve()))
    sys.stdout.buffer.write(canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
