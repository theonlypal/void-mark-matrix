"""PA1 qualifying set from the July 2026 Cross-Vendor Semantic Void Matrix trial-level table. No network operations.

Source: github.com/theonlypal/void-matrix-complete-analysis, commit 3fd330869c1a4a410047bc70b3f661f1a9d69aca,
analysis/tables/trial_level.csv. Rows: system_id primary, budget 4000, prompt_text one of the three null inputs,
every study and parameter track. Rate: (V0 + V1 + V2 + VU) / rows, per model_id. Qualifying: rate >= 0.90.
"""
import argparse
import collections
import csv
import hashlib
import json
import sys
from pathlib import Path
from frozen import STUDY_A_NULL_INPUTS

SOURCE = {"repository": "https://github.com/theonlypal/void-matrix-complete-analysis",
          "commit": "3fd330869c1a4a410047bc70b3f661f1a9d69aca", "path": "analysis/tables/trial_level.csv",
          "sha256": "139332401aa7213b6e725df7e79707940eee754d68ed05c56011be94f728b7d3",
          "git_blob": "192921990ce21183ac0b44934cd3d4cc3c8a41dc"}
THRESHOLD = 0.90


def rates(path):
    data = Path(path).read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE["sha256"], "trial_level.csv differs from the pinned commit"
    tally = collections.defaultdict(lambda: [0, 0])
    for row in csv.DictReader(data.decode("utf-8").splitlines()):
        if row["system_id"] == "primary" and row["budget"] == "4000" and row["prompt_text"] in STUDY_A_NULL_INPUTS:
            tally[row["model_id"]][0] += row["classification"] in ("V0", "V1", "V2", "VU")
            tally[row["model_id"]][1] += 1
    return {m: {"voids": v, "trials": n, "qualifies": v >= THRESHOLD * n} for m, (v, n) in sorted(tally.items())}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("trial_level_csv", type=Path)
    result = rates(p.parse_args().trial_level_csv)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
