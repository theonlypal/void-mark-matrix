"""Frozen runner. Raw persistence precedes classification and progress."""
import argparse
import json
import math
import os
from pathlib import Path
import platform
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
import httpx
import regex
import vendors
import xclassify
from frozen import (ROOT, FROZEN_TAG, VENDORS, PINNED, STUDIES, MAX_SPEND_USD, CONCURRENCY_PER_VENDOR, CREDENTIAL_ENV,
                    PRICES_USD_PER_MTOK, canonical, digest, request, preflight_request, load_schedule, usd, price_current,
                    prereg_canonical)
from verify import (FOLDERS, Ledger, attempt_path, charge, compute_verdict, counts_as_try, definitive_outcome,
                    excluded_record, experiment_of, folder_name, interrupted, replay, reservation)

RESPONSE_HEADERS = {"request-id", "x-request-id", "date", "content-type", "retry-after", "x-should-retry"}
BACKOFF_SECONDS = [5, 15, 30]
MAX_ATTEMPTS = 4
RETRY_AFTER_MAX_SECONDS = 120
TIMEOUTS = {v: httpx.Timeout(connect=30, read=vendors.READ_TIMEOUT_SECONDS[v], write=30, pool=30) for v in VENDORS}


def utc():
    return datetime.now(timezone.utc).isoformat()


def utc_date():
    return datetime.now(timezone.utc).date().isoformat()


def save_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def save_json(path, data):
    save_bytes(path, canonical(data) + b"\n")


def replace_json(path, data):
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        f.write(canonical(data) + b"\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def environment():
    return {"python": platform.python_version(), "httpx": httpx.__version__, "regex": regex.__version__}


def check_environment():
    env = environment()
    for name, version in PINNED.items():
        assert env[name] == version, f"{name} {env[name]} differs from pinned {version}"
    return env


def check_prices():
    missing = sorted(m for m, p in PRICES_USD_PER_MTOK.items() if p is None)
    assert not missing, "Unpriced models: " + ", ".join(missing)
    today = utc_date()
    expired = sorted(m for m in PRICES_USD_PER_MTOK if not price_current(m, today))
    assert not expired, "Frozen prices past their documented end date: " + ", ".join(expired)


def check_freeze():
    commit = git("rev-parse", "HEAD")
    tagged = git("rev-parse", FROZEN_TAG + "^{commit}")
    if commit != tagged:
        assert subprocess.run(["git", "merge-base", "--is-ancestor", tagged, commit], cwd=ROOT).returncode == 0, \
            "HEAD does not descend from the frozen tag " + FROZEN_TAG
        assert git("diff", "--numstat", tagged, commit).split() == ["1", "0", "PREREG.md"], \
            "HEAD differs from the frozen tag beyond one added line in PREREG.md"
    protocol = json.loads((ROOT / "protocol.json").read_bytes())
    assert digest(prereg_canonical((ROOT / "PREREG.md").read_bytes())) == protocol["prereg"]["canonical_sha256"], \
        "PREREG.md differs from the frozen preregistration beyond the permitted DOI line"
    assert not git("status", "--porcelain", "--untracked-files=all"), "Working tree must be clean"
    for study in FOLDERS:
        load_schedule(study)
    return commit


def credentials():
    keys = {v: os.environ.get(name, "").strip() for v, name in CREDENTIAL_ENV.items()}
    missing = [CREDENTIAL_ENV[v] for v, k in keys.items() if not k]
    assert not missing, "Missing credential environment variables: " + ", ".join(missing)
    return keys


def make_clients(keys, transports=None):
    return {v: httpx.Client(headers=vendors.headers(v, keys[v]), timeout=TIMEOUTS[v], trust_env=False, follow_redirects=False,
                            transport=(transports or {}).get(v) or httpx.HTTPTransport(retries=0)) for v in VENDORS}


class Events:
    def __init__(self, path, ledger):
        if ledger.seq == 0:
            assert not path.exists(), "Event log already exists"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.seq = ledger.seq
        self.previous = ledger.head

    def add(self, event, data):
        self.seq += 1
        row = {"seq": self.seq, "prev_hash": self.previous, "event": event, "data": data, "timestamp_utc": utc()}
        row["event_hash"] = digest(canonical(row))
        with self.path.open("ab") as f:
            f.write(canonical(row) + b"\n")
            f.flush()
            os.fsync(f.fileno())
        self.previous = row["event_hash"]


def attempt(client, folder, experiment, vendor, url, body, label):
    folder.mkdir(parents=True, exist_ok=False)
    req = client.build_request("POST", url, content=body, headers={"content-type": "application/json"})
    assert req.content == body
    save_bytes(folder / "request.bin", req.content)
    sent_headers = {k: ("REDACTED" if k.lower() in vendors.CREDENTIAL_HEADERS else v) for k, v in req.headers.items()}
    meta = {"slot_id": label, "vendor": vendor, "timestamp_utc": utc(), "url": str(req.url), "request_headers": sent_headers,
            "request_sha256": digest(req.content), "http_status": None, "response_headers": {},
            "response_sha256": None, "classifier_input_sha256": None, "transport_error": None}
    started = time.monotonic()
    raw = b""
    try:
        response = client.send(req)
        raw = response.content
        meta["http_status"] = response.status_code
        meta["response_headers"] = {k: v for k, v in response.headers.items() if k.lower() in RESPONSE_HEADERS}
    except httpx.TransportError as exc:
        meta["transport_error"] = {"type": type(exc).__name__, "retry_eligible": True}
    except httpx.HTTPError as exc:
        meta["transport_error"] = {"type": type(exc).__name__, "retry_eligible": False}
    except KeyboardInterrupt:
        meta["transport_error"] = {"type": "KeyboardInterrupt", "retry_eligible": True}
    save_bytes(folder / "response.bin", raw)
    mapped, result = xclassify.classify_attempt(experiment, vendor, meta["http_status"], raw)
    meta.update(duration_seconds=time.monotonic() - started, completed_at_utc=utc(), response_sha256=digest(raw),
                classifier_input_sha256=digest(mapped))
    save_bytes(folder / "classifier_input.bin", mapped)
    save_json(folder / "attempt.json", meta)
    save_json(folder / "classification.json", result)
    return meta, result


def retry_eligible(meta, result):
    if meta["transport_error"]:
        return meta["transport_error"]["retry_eligible"]
    status = meta["http_status"]
    if result["class"] == "QE":
        return False
    return status == 429 or (isinstance(status, int) and 500 <= status <= 599)


def retry_wait(meta, tries):
    value = meta["response_headers"].get("retry-after")
    status = meta["http_status"]
    if value is not None and (status == 429 or (isinstance(status, int) and 500 <= status <= 599)):
        try:
            return max(0, min(math.ceil(float(value)), RETRY_AFTER_MAX_SECONDS)), "retry-after"
        except (ValueError, OverflowError):
            pass
    return BACKOFF_SECONDS[tries - 1], "backoff"


def retry_sleep(seconds, stop):
    stop.wait(seconds)


def other_spent(output, study, verdict):
    """Spend already recorded in the other output folders; the cap covers preflight and both studies together."""
    total = 0
    for other in FOLDERS:
        folder = output / folder_name(other)
        if other != study and (folder / "events.jsonl").exists():
            total += replay(folder, other, load_schedule(other), verdict).spent()
    return total


class Run:
    """Shared state of one execution. Every ledger change and event append happens under one lock."""

    def __init__(self, study, folder, clients, ledger, events, verdict, baseline):
        self.study, self.folder, self.clients = study, folder, clients
        self.ledger, self.events, self.verdict, self.baseline = ledger, events, verdict, baseline
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.status, self.reason = None, None

    def halt(self, status, reason):
        if self.status is None or (status == "INCONCLUSIVE" and self.status != "INCONCLUSIVE"):
            self.status, self.reason = status, reason
        self.stop.set()

    def variant(self, slot):
        return self.verdict["models"][slot["model"]]["study_a_variant"] if self.study == "A" else "omit"

    def finish_slot(self, slot, n):
        path = attempt_path(self.folder, slot["slot_id"], n)
        meta = json.loads((path / "attempt.json").read_bytes())
        result = json.loads((path / "classification.json").read_bytes())
        record = {"slot_id": slot["slot_id"], "attempt": n, "class": result["class"], "void": result["void"],
                  "model_completion": result["model_completion"], "http_status": meta["http_status"],
                  "variant": self.variant(slot), "requested_model": slot["model"], "returned_model": result["returned_model"],
                  "response_id": result["response_id"],
                  "request_id": meta["response_headers"].get("request-id") or meta["response_headers"].get("x-request-id"),
                  "request_sha256": meta["request_sha256"], "response_sha256": meta["response_sha256"]}
        target = self.folder / "definitive" / (slot["slot_id"] + ".json")
        if target.exists():
            assert json.loads(target.read_bytes()) == record, "Existing definitive record differs"
        else:
            save_json(target, record)
        self.ledger.complete(record)
        self.events.add("slot_completed", record)
        print(f"{self.study} {len(self.ledger.definitive)} {slot['slot_id']} {slot['model']} {result['class']}", flush=True)
        return self.study == "preflight" or record["returned_model"] == slot["model"]

    def run_slot(self, slot):
        study, folder, ledger, events = self.study, self.folder, self.ledger, self.events
        slot_id, variant = slot["slot_id"], self.variant(slot)
        if study == "preflight":
            url, body = preflight_request(slot["check"], slot["vendor"], slot["model"])
        else:
            url, body = request(study, slot, variant)
        body = canonical(body)
        assert digest(body) == slot["request_sha256"][variant], "Request bytes differ from schedule"
        reserved = reservation(study, slot)
        while True:
            with self.lock:
                if self.stop.is_set():
                    return
                if ledger.tries[slot_id] >= MAX_ATTEMPTS:
                    return self.halt("INCONCLUSIVE", "No definitive model completion for " + slot_id)
                if not price_current(slot["model"], utc_date()):
                    return self.halt("PAUSED", "price expired")
                if self.baseline + ledger.spent() + ledger.in_flight() + reserved > MAX_SPEND_USD * 1_000_000_000:
                    return self.halt("PAUSED", "spend cap")
                n = ledger.attempts[slot_id] + 1
                ledger.start(slot_id, n, reserved, slot["vendor"])
                events.add("attempt_started", {"slot_id": slot_id, "attempt": n, "variant": variant,
                                               "request_sha256": slot["request_sha256"][variant], "reserved_usd": usd(reserved)})
            meta, result = attempt(self.clients[slot["vendor"]], attempt_path(folder, slot_id, n),
                                   experiment_of(study, slot), slot["vendor"], url, body, slot_id)
            with self.lock:
                kind, amount = charge(meta, result, reserved, slot["model"])
                spent = ledger.settle(slot_id, n, amount, counts_as_try(meta, result))
                events.add("attempt_persisted", {"slot_id": slot_id, "attempt": n, "http_status": meta["http_status"],
                                                 "response_sha256": meta["response_sha256"], "class": result["class"],
                                                 "model_completion": result["model_completion"], "charge": kind,
                                                 "cost_usd": usd(amount), "interrupted": interrupted(meta),
                                                 "spent_usd": usd(spent)})
                if interrupted(meta):
                    return self.halt("PAUSED", "interrupted")
                if result["class"] == "QE":
                    return self.halt("PAUSED", "provider quota")
                if definitive_outcome(study, meta, result):
                    ledger.awaiting[slot_id] = n
                    if not self.finish_slot(slot, n):
                        self.halt("INCONCLUSIVE", "Returned model differs from requested model")
                    return
                if not retry_eligible(meta, result) or ledger.tries[slot_id] >= MAX_ATTEMPTS:
                    return self.halt("INCONCLUSIVE", "No definitive model completion for " + slot_id)
                seconds, source = retry_wait(meta, ledger.tries[slot_id])
                events.add("retry_wait", {"slot_id": slot_id, "attempt": n, "seconds": seconds, "source": source})
                print(f"{study} {slot_id} attempt {n} http={meta['http_status']} wait {seconds}s ({source})", flush=True)
            retry_sleep(seconds, self.stop)

    def worker(self, pending):
        while not self.stop.is_set():
            try:
                slot = pending.get_nowait()
            except queue.Empty:
                return
            try:
                self.run_slot(slot)
            except KeyboardInterrupt:
                with self.lock:
                    self.halt("PAUSED", "interrupted")
            except Exception as exc:
                with self.lock:
                    self.halt("INCONCLUSIVE", str(exc) if isinstance(exc, (AssertionError, RuntimeError)) else type(exc).__name__)


def load_verdict(output, commit, frozen):
    path = output / "preflight" / "verdict.json"
    assert path.exists(), "A complete preflight verdict is required"
    verdict = json.loads(path.read_bytes())
    assert (verdict["commit"], verdict["frozen"]) == (commit, frozen), "Preflight ran on a different commit or freeze mode"
    return verdict


def execute(study, output, clients, frozen=True):
    """Run preflight or one study to COMPLETE, PAUSED or INCONCLUSIVE. Returns True on COMPLETE."""
    commit = check_freeze() if frozen else head()
    env = check_environment()
    check_prices()
    schedule = load_schedule(study)
    slots = {s["slot_id"]: s for s in schedule}
    verdict = None if study == "preflight" else load_verdict(output, commit, frozen)
    folder = output / folder_name(study)
    baseline = other_spent(output, study, verdict)
    if folder.exists():
        ledger = replay(folder, study, schedule, verdict)
        assert ledger.status not in ("COMPLETE", "INCONCLUSIVE"), f"Run is {ledger.status}; refusing rerun"
        assert (ledger.run["commit"], ledger.run["frozen"], ledger.run["environment"]) == (commit, frozen, env), \
            "Resume requires the commit, freeze mode and environment of the original run"
        events = Events(folder / "events.jsonl", ledger)
        events.add("run_resumed", {"commit": commit, "completed": len(ledger.definitive), "spent_usd": usd(ledger.spent()),
                                   "other_folders_spent_usd": usd(baseline)})
    else:
        ledger = Ledger()
        events = Events(folder / "events.jsonl", ledger)
        events.add("run_started", {"study": study, "commit": commit, "tag": FROZEN_TAG, "frozen": frozen,
                                   "environment": env, "slots": len(schedule), "max_spend_usd": MAX_SPEND_USD,
                                   "other_folders_spent_usd": usd(baseline),
                                   "concurrency_per_vendor": CONCURRENCY_PER_VENDOR})
    run = Run(study, folder, clients, ledger, events, verdict, baseline)
    try:
        for slot_id, (n, reserved, _) in sorted(ledger.open.items()):
            spent = ledger.settle(slot_id, n, reserved, False)
            events.add("attempt_abandoned", {"slot_id": slot_id, "attempt": n, "spent_usd": usd(spent)})
        for slot_id, n in sorted(ledger.awaiting.items()):
            if not run.finish_slot(slots[slot_id], n):
                run.halt("INCONCLUSIVE", "Returned model differs from requested model")
        if study != "preflight":
            if any(r["class"] != "OP" and r["returned_model"] != r["requested_model"] for r in ledger.definitive.values()):
                run.halt("INCONCLUSIVE", "Returned model differs from requested model")
            for slot in schedule:
                if verdict["models"][slot["model"]]["status"] == "OP" and slot["slot_id"] not in ledger.definitive:
                    record = excluded_record(slot, verdict)
                    save_json(folder / "definitive" / (slot["slot_id"] + ".json"), record)
                    ledger.exclude(record)
                    events.add("slot_excluded", record)
        pending = {v: queue.Queue() for v in VENDORS}
        for slot in schedule:
            if slot["slot_id"] not in ledger.definitive:
                pending[slot["vendor"]].put(slot)
        workers = [threading.Thread(target=run.worker, args=(pending[v],), daemon=True)
                   for v in VENDORS for _ in range(CONCURRENCY_PER_VENDOR)]
        if not run.stop.is_set():
            for w in workers:
                w.start()
        interrupted_once = False
        while any(w.is_alive() for w in workers):
            try:
                for w in workers:
                    w.join(0.2)
            except KeyboardInterrupt:
                if interrupted_once:
                    raise
                interrupted_once = True
                with run.lock:
                    run.halt("PAUSED", "interrupted")
                    in_flight = len(ledger.open)
                print(f"{study} interrupt: finishing {in_flight} in-flight requests; interrupt again to exit without a terminal record",
                      flush=True)
        if run.status is None:
            assert len(ledger.definitive) == len(schedule), "Slots remain without a definitive record"
            if frozen:
                check_freeze()
            run.status = "COMPLETE"
            if study == "preflight":
                replace_json(folder / "verdict.json", {"commit": commit, "frozen": frozen, "tag": FROZEN_TAG, "environment": env,
                                                       "models": compute_verdict(ledger, schedule), "timestamp_utc": utc()})
    except Exception as exc:
        run.halt("INCONCLUSIVE", str(exc) if isinstance(exc, (AssertionError, RuntimeError)) else type(exc).__name__)
    status, reason = run.status, run.reason
    summary = {"completed": len(ledger.definitive), "spent_usd": usd(ledger.spent()), "spent_by_vendor_usd": ledger.by_vendor()}
    if status == "COMPLETE":
        events.add("run_completed", summary)
    elif status == "PAUSED":
        events.add("run_paused", dict(summary, reason=reason))
    else:
        events.add("run_stopped", dict(summary, reason=reason, result="INCONCLUSIVE"))
    replace_json(folder / "completion.json", {"study": study, "status": status, "reason": reason,
                                              "completed_slots": len(ledger.definitive), "scheduled_slots": len(schedule),
                                              "spent_usd": usd(ledger.spent()), "spent_by_vendor_usd": ledger.by_vendor(),
                                              "other_folders_spent_usd": usd(baseline), "max_spend_usd": MAX_SPEND_USD,
                                              "event_chain_head": events.previous, "completed_at_utc": utc()})
    print(f"{study} {status} {len(ledger.definitive)}/{len(schedule)} spent_usd={usd(ledger.spent()):.6f}"
          + (f" reason={reason}" if reason else ""), flush=True)
    return status == "COMPLETE"


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight")
    run = sub.add_parser("run")
    run.add_argument("--study", choices=STUDIES, required=True)
    for s in (pre, run):
        s.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    output = args.output.resolve()
    assert output != ROOT and ROOT not in output.parents, "Output must be outside the runner repository"
    clients = make_clients(credentials())
    try:
        return 0 if execute("preflight" if args.command == "preflight" else args.study, output, clients) else 2
    finally:
        for c in clients.values():
            c.close()


if __name__ == "__main__":
    sys.exit(main())
