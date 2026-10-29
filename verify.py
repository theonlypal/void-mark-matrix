"""Offline verification of a run output and event-log replay. No network operations."""
import argparse
import collections
import json
from pathlib import Path
import sys
import vendors
import xclassify
from frozen import (STUDIES, EXPERIMENT_OF, VENDORS, MODELS, MAX_SPEND_USD, canonical, digest, request_bytes,
                    preflight_request, load_schedule, max_tokens_of, reservation_nano_usd, usage_nano_usd, usd)

TERMINAL_EVENTS = {"run_completed": "COMPLETE", "run_paused": "PAUSED", "run_stopped": "INCONCLUSIVE"}
FOLDERS = ("preflight",) + STUDIES


def folder_name(study):
    return "preflight" if study == "preflight" else "study" + study


def condition_key(study, slot):
    return (slot["vendor"], slot["model"], slot["input"] if study == "A" else slot["cell"])


def attempt_path(folder, slot_id, n):
    return folder / "attempts" / slot_id / f"attempt-{n:02d}"


def experiment_of(study, slot):
    return EXPERIMENT_OF["A" if slot["check"].startswith("A") else "B"] if study == "preflight" else EXPERIMENT_OF[study]


def frozen_request(study, slot, variant):
    if study == "preflight":
        assert variant == "omit", "Preflight slots carry one request"
        return canonical(preflight_request(slot["check"], slot["vendor"], slot["model"])[1])
    return request_bytes(study, slot, variant)


def reservation(study, slot):
    max_tokens = max_tokens_of("A" if slot["check"].startswith("A") else "B") if study == "preflight" else max_tokens_of(study)
    return reservation_nano_usd(slot["model"], max_tokens)


def interrupted(meta):
    return (meta["transport_error"] or {}).get("type") == "KeyboardInterrupt"


def counts_as_try(meta, result):
    return not interrupted(meta) and result["class"] != "QE"


def definitive_outcome(study, meta, result):
    """A model completion ends a study slot; a preflight slot ends on its first attempt that is neither interrupted nor QE."""
    if study == "preflight":
        return counts_as_try(meta, result)
    return result["model_completion"]


def charge(meta, result, reserved, model):
    """Reported usage replaces the reservation; a 2xx without usage or a transport failure keeps it; HTTP errors cost 0."""
    status = meta["http_status"]
    ok = isinstance(status, int) and 200 <= status <= 299
    cost = usage_nano_usd(model, result["usage"]) if ok and result["usage"] is not None else None
    if cost is not None:
        return "usage", cost
    if ok or meta["transport_error"]:
        return "reservation", reserved
    return "none", 0


class Ledger:
    """Spend and progress state of one output folder, rebuilt identically by the runner and by replay."""

    def __init__(self):
        self.committed = collections.Counter()
        self.attempts = collections.Counter()
        self.tries = collections.Counter()
        self.definitive = {}
        self.open = {}
        self.awaiting = {}
        self.status = None
        self.run = None
        self.seq = 0
        self.head = "0" * 64

    def spent(self):
        return sum(self.committed.values())

    def by_vendor(self):
        return {v: usd(self.committed[v]) for v in VENDORS}

    def in_flight(self):
        return sum(reserved for _, reserved, _ in self.open.values())

    def start(self, slot_id, n, reserved, vendor):
        assert slot_id not in self.open and slot_id not in self.definitive and slot_id not in self.awaiting, "Attempt out of order"
        assert n == self.attempts[slot_id] + 1, "Attempt number out of order"
        self.attempts[slot_id] = n
        self.open[slot_id] = (n, reserved, vendor)

    def settle(self, slot_id, n, amount, counted):
        assert self.open.get(slot_id, (None,))[0] == n, "Attempt settlement out of order"
        vendor = self.open.pop(slot_id)[2]
        self.committed[vendor] += amount
        if counted:
            self.tries[slot_id] += 1
        return self.spent()

    def complete(self, record):
        assert self.awaiting.get(record["slot_id"]) == record["attempt"], "Definitive record does not follow its completion"
        assert record["slot_id"] not in self.definitive, "Duplicate definitive record"
        self.definitive[record["slot_id"]] = record
        del self.awaiting[record["slot_id"]]

    def exclude(self, record):
        assert record["slot_id"] not in self.definitive and not self.attempts[record["slot_id"]], "Excluded slot was attempted"
        self.definitive[record["slot_id"]] = record


def check_chain(path):
    previous, seq, rows = "0" * 64, 0, []
    for line in path.read_bytes().splitlines():
        row = json.loads(line)
        seq += 1
        assert row["seq"] == seq, "Event sequence gap"
        assert row["prev_hash"] == previous, "Event chain break"
        expected = row.pop("event_hash")
        assert digest(canonical(row)) == expected, "Event hash mismatch"
        previous = expected
        rows.append(row)
    return rows, previous


def check_attempt(experiment, vendor, folder, body):
    meta = json.loads((folder / "attempt.json").read_bytes())
    request = (folder / "request.bin").read_bytes()
    response = (folder / "response.bin").read_bytes()
    mapped = (folder / "classifier_input.bin").read_bytes()
    assert request == body, "Request bytes differ from frozen request"
    assert digest(request) == meta["request_sha256"], "Request hash mismatch"
    assert digest(response) == meta["response_sha256"], "Response hash mismatch"
    derived, result = xclassify.classify_attempt(experiment, vendor, meta["http_status"], response)
    assert derived == mapped, "Extractor output does not reproduce"
    assert digest(mapped) == meta["classifier_input_sha256"], "Classifier input hash mismatch"
    for name in vendors.CREDENTIAL_HEADERS:
        assert meta["request_headers"].get(name) in (None, "REDACTED"), "Credential persisted"
    assert result == json.loads((folder / "classification.json").read_bytes()), "Classification does not reproduce"
    return meta, result


def replay(folder, study, schedule, verdict=None):
    rows, head = check_chain(folder / "events.jsonl")
    slots = {s["slot_id"]: s for s in schedule}
    ledger = Ledger()
    for i, row in enumerate(rows):
        event, data = row["event"], row["data"]
        if i == 0:
            assert event == "run_started" and data["study"] == study and data["slots"] == len(schedule), "Bad run start"
            ledger.run = data
        elif event == "run_resumed":
            assert ledger.status not in ("COMPLETE", "INCONCLUSIVE"), "Resumed a terminal run"
            assert data["spent_usd"] == usd(ledger.spent()), "Spend does not replay"
            ledger.status = None
        elif event == "slot_excluded":
            slot = slots[data["slot_id"]]
            assert verdict is not None and verdict["models"][slot["model"]]["status"] == "OP", "Excluded slot of a model that passed preflight"
            assert data == excluded_record(slot, verdict), "Bad exclusion record"
            ledger.exclude(data)
        elif event == "attempt_started":
            slot = slots[data["slot_id"]]
            reserved = reservation(study, slot)
            expected_variant = "omit" if study != "A" else verdict["models"][slot["model"]]["study_a_variant"]
            assert data["variant"] == expected_variant, "Variant differs from the preflight verdict"
            assert data["request_sha256"] == slot["request_sha256"][data["variant"]] and data["reserved_usd"] == usd(reserved), "Bad reservation"
            ledger.start(data["slot_id"], data["attempt"], reserved, slot["vendor"])
        elif event == "attempt_persisted":
            slot = slots[data["slot_id"]]
            assert data["slot_id"] in ledger.open, "Attempt persisted without start"
            variant = "omit" if study != "A" else verdict["models"][slot["model"]]["study_a_variant"]
            meta, result = check_attempt(experiment_of(study, slot), slot["vendor"],
                                         attempt_path(folder, data["slot_id"], data["attempt"]),
                                         frozen_request(study, slot, variant))
            kind, amount = charge(meta, result, ledger.open[data["slot_id"]][1], slot["model"])
            observed = (data["response_sha256"], data["class"], data["model_completion"], data["charge"], data["interrupted"])
            assert observed == (meta["response_sha256"], result["class"], result["model_completion"], kind, interrupted(meta)), \
                "Persisted event differs from attempt files"
            assert data["spent_usd"] == usd(ledger.settle(data["slot_id"], data["attempt"], amount, counts_as_try(meta, result))), \
                "Spend does not replay"
            if definitive_outcome(study, meta, result):
                ledger.awaiting[data["slot_id"]] = data["attempt"]
        elif event == "attempt_abandoned":
            assert data["slot_id"] in ledger.open, "Abandoned attempt without start"
            spent = ledger.settle(data["slot_id"], data["attempt"], ledger.open[data["slot_id"]][1], False)
            assert data["spent_usd"] == usd(spent), "Spend does not replay"
        elif event == "retry_wait":
            assert data["slot_id"] in slots and data["slot_id"] not in ledger.open, "Bad retry wait"
        elif event == "slot_completed":
            ledger.complete(data)
        elif event in TERMINAL_EVENTS:
            assert ledger.status is None, "Second terminal event without resume"
            assert data["spent_usd"] == usd(ledger.spent()) and data["spent_by_vendor_usd"] == ledger.by_vendor(), "Spend does not replay"
            ledger.status = TERMINAL_EVENTS[event]
        else:
            raise AssertionError("Unknown event " + event)
    ledger.seq, ledger.head = len(rows), head
    return ledger


def excluded_record(slot, verdict):
    return {"slot_id": slot["slot_id"], "attempt": 0, "class": "OP", "void": False, "requested_model": slot["model"],
            "returned_model": None, "response_id": None, "request_id": None, "request_sha256": None,
            "response_sha256": None, "preflight": verdict["models"][slot["model"]]["checks"]}


def preflight_passes(record, model):
    return (record["class"] not in ("OP",) and record["model_completion"] and record["http_status"] == 200
            and record["returned_model"] == model and isinstance(record["response_id"], str) and record["response_id"] != "")


def compute_verdict(ledger, schedule):
    models = {}
    for vendor in VENDORS:
        for model in MODELS[vendor]:
            checks = {s["check"]: ledger.definitive[s["slot_id"]] for s in schedule if s["model"] == model}
            ok = {c: preflight_passes(r, model) for c, r in checks.items()}
            variant = "t0" if ok.get("A-t0") else "omit" if ok["A-omit"] else None
            status = "PASS" if variant and ok["B"] else "OP"
            models[model] = {"vendor": vendor, "status": status, "study_a_variant": variant if status == "PASS" else None,
                             "checks": {c: {"pass": ok[c], "slot_id": r["slot_id"], "class": r["class"],
                                            "http_status": r["http_status"], "returned_model": r["returned_model"],
                                            "response_id": r["response_id"], "response_sha256": r["response_sha256"]}
                                        for c, r in sorted(checks.items())}}
    return models


def check_folder(folder, study, schedule, ledger):
    slots = {s["slot_id"]: s for s in schedule}
    completion = json.loads((folder / "completion.json").read_bytes())
    assert completion["event_chain_head"] == ledger.head, "Completion does not match event chain head"
    assert completion["status"] == ledger.status, "Completion status differs from event log"
    assert completion["spent_usd"] == usd(ledger.spent()), "Completion spend differs from event log"
    assert completion["spent_by_vendor_usd"] == ledger.by_vendor(), "Completion vendor spend differs from event log"
    assert completion["completed_slots"] == len(ledger.definitive), "Completed slot count mismatch"
    for slot_dir in (folder / "attempts").iterdir() if (folder / "attempts").exists() else []:
        assert slot_dir.name in slots, "Attempt folder for unscheduled slot " + slot_dir.name
        allowed = {f"attempt-{n:02d}" for n in range(1, ledger.attempts[slot_dir.name] + 1)}
        assert {p.name for p in slot_dir.iterdir()} <= allowed, "Attempt folder absent from event log"
    files = {p.name[:-len(".json")] for p in (folder / "definitive").iterdir()} if (folder / "definitive").exists() else set()
    assert files == set(ledger.definitive), "Definitive records differ from event log"
    for slot_id, record in ledger.definitive.items():
        assert json.loads((folder / "definitive" / (slot_id + ".json")).read_bytes()) == record, "Definitive record differs"
        assert record["requested_model"] == slots[slot_id]["model"]
        if record["class"] == "OP":
            assert not (folder / "attempts" / slot_id).exists(), "Excluded slot has attempt files"
            continue
        assert record["attempt"] == ledger.attempts[slot_id], "Definitive record is not the last attempt"
        path = attempt_path(folder, slot_id, record["attempt"])
        result = json.loads((path / "classification.json").read_bytes())
        meta = json.loads((path / "attempt.json").read_bytes())
        assert record["class"] == result["class"] and record["response_sha256"] == meta["response_sha256"]
    if ledger.status == "COMPLETE":
        assert set(ledger.definitive) == set(slots), "COMPLETE without exactly one definitive record per scheduled slot"


def verify_preflight(output):
    folder = output / "preflight"
    schedule = load_schedule("preflight")
    ledger = replay(folder, "preflight", schedule)
    check_folder(folder, "preflight", schedule, ledger)
    verdict_path = folder / "verdict.json"
    if ledger.status != "COMPLETE":
        assert not verdict_path.exists(), "Verdict without a complete preflight"
        return ledger, None
    verdict = json.loads(verdict_path.read_bytes())
    assert verdict["models"] == compute_verdict(ledger, schedule), "Verdict does not reproduce from preflight records"
    assert verdict["commit"] == ledger.run["commit"] and verdict["frozen"] == ledger.run["frozen"], "Verdict commit differs"
    return ledger, verdict


def verify_study(output, study, verdict):
    folder = output / folder_name(study)
    schedule = load_schedule(study)
    assert verdict is not None, "A complete preflight verdict is required"
    ledger = replay(folder, study, schedule, verdict)
    assert ledger.run["commit"] == verdict["commit"] and ledger.run["frozen"] == verdict["frozen"], "Study ran on a different commit than preflight"
    check_folder(folder, study, schedule, ledger)
    slots = {s["slot_id"]: s for s in schedule}
    counts = collections.defaultdict(collections.Counter)
    for slot_id, record in ledger.definitive.items():
        counts[condition_key(study, slots[slot_id])][record["class"]] += 1
    return ledger, counts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--study", choices=STUDIES)
    args = p.parse_args()
    output = args.output.resolve()
    failures, total = 0, 0
    try:
        ledger, verdict = verify_preflight(output)
        total += ledger.spent()
        print(f"preflight VERIFY PASS {ledger.status} definitive={len(ledger.definitive)} spent_usd={usd(ledger.spent()):.6f}")
        for model, v in (verdict or {}).get("models", {}).items():
            print(f"  {v['vendor']} | {model} | {v['status']} | study_a_variant={v['study_a_variant']}")
    except (AssertionError, KeyError, OSError, ValueError) as exc:
        print(f"preflight VERIFY FAIL: {exc}")
        return 1
    for study in [args.study] if args.study else STUDIES:
        if not (output / folder_name(study)).exists():
            continue
        try:
            ledger, counts = verify_study(output, study, verdict)
        except (AssertionError, KeyError, OSError, ValueError) as exc:
            failures += 1
            print(f"study{study} VERIFY FAIL: {exc}")
            continue
        total += ledger.spent()
        print(f"study{study} VERIFY PASS definitive={len(ledger.definitive)}/{len(load_schedule(study))} spent_usd={usd(ledger.spent()):.6f}")
        print(f"study{study} {ledger.status} " + " ".join(f"{v}={s:.6f}" for v, s in ledger.by_vendor().items()))
        for key in sorted(counts, key=str):
            print("  " + " | ".join(map(str, key)) + " | " + " ".join(f"{c}={n}" for c, n in sorted(counts[key].items())))
    if not args.study:
        within = total <= MAX_SPEND_USD * 1_000_000_000
        failures += not within
        print(f"total spent_usd={usd(total):.6f} cap_usd={MAX_SPEND_USD} {'WITHIN CAP' if within else 'CAP EXCEEDED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
