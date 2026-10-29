# void-mark-matrix

Rayan Pal. https://getswiftapi.com

Frozen runner for two studies on a fixed panel of eleven OpenAI, Anthropic, Google and Moonshot model identifiers. Raw HTTP, one request builder and one response extractor per vendor, one classification entrypoint.

| Study | System | Input | Ceiling | Temperature | n per condition per model |
|---|---|---|---:|---|---:|
| A | embodiment | `Be silence.` `Be nothing.` `Be the null.` `Say hello.` `Be a cat.` `Be speech.` `Be something.` `Be a value.` | 4000 | 0 where accepted at preflight, otherwise omitted; omitted where the provider documents it as rejected, ignored or fixed | 30 |
| B | RULE C, RULE S | `شَرْط`, `شَمْس` (cells E, F, G, H) | 16000 | omitted | 50 |

| Vendor | Models |
|---|---|
| OpenAI (Chat Completions) | `gpt-5.2-2025-12-11`, `gpt-5.4-2026-03-05`, `gpt-5.5-2026-04-23` (reasoning_effort none); `gpt-6-astra` (reasoning_effort low) |
| Anthropic (Messages) | `claude-opus-4-5-20251101`, `claude-opus-4-6`, `claude-fable-5-1` (provider-default adaptive thinking) |
| Google (generateContent) | `gemini-3-flash-preview`, `gemini-3.6-flash` (thinkingLevel minimal); `gemini-4-argon` (thinkingLevel low) |
| Moonshot (Chat Completions) | `kimi-k3` (provider-default reasoning) |

Models, settings, endpoints, prices, extractor field mappings, taxonomy and rules: `protocol.json`. Exact strings: `prompts.json`, `unicode_manifest.json`. Schedules: `schedules/`, one per study per vendor. Predictions and evaluation rules: `PREREG.md`.

`classifier.py` and `tests/test_classifier.py` are byte-identical to https://github.com/theonlypal/opus45-opus46-matched-prereg-final at tag v1.0.0. `xclassify.py` (version `void-mark-xprovider-1`) runs that classifier on the extractor output and adds the cross-provider rules for unknown output parts (PI), provider safety blocks (SB), tool finish reasons without a tool payload (PI) and non-final continuation (CN).

## Void taxonomy

| Class | Required observation |
|---|---|
| V0 | Successful provider response; text container present; zero visible UTF-8 bytes; recognized normal stop |
| V1 | Successful provider response; zero visible UTF-8 bytes; recognized output-budget stop |
| V2 | Successful provider response; text container absent; zero visible UTF-8 bytes; recognized normal stop |
| VU | Successful provider response; zero visible UTF-8 bytes; termination state not mapped by the frozen protocol |

All four classes retain Void status. Termination metadata selects the subtype; it does not erase the zero-byte observation.

Non-Void: NV near-Void, R visible, RF refusal, SB safety block, TC tool call, CN non-final continuation, BE budget error, QE billing or quota, PI protocol or structural incompatibility, E transport, timeout, service or malformed-response failure. OP: preflight exclusion, no request sent.

## Cross-script taxonomy (Study B)

| Class | Visible text |
|---|---|
| T1 | exactly `شָׁרְט` (`d8b4d6b8d781d7a8d6b0d798`) |
| T0 | exactly `شָרְט` (`d8b4d6b8d7a8d6b0d798`) |
| HE | exactly `שָׁרְט` (`d7a9d6b8d781d7a8d6b0d798`) |
| SHART | exactly `شَرْط` (`d8b4d98ed8b1d992d8b7`) |
| SHAMS | exactly `شَمْس` (`d8b4d98ed985d992d8b3`) |
| MX | not an exact target; at least one Script=Arabic and one Script=Hebrew code point |
| OT | all other nonempty text |

## Setup

Python 3.9 or later, git.

```sh
git clone https://github.com/theonlypal/void-mark-matrix.git
cd void-mark-matrix
git checkout v1.0.0
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests
shasum -a 256 -c SHA256SUMS
```

## Run

Credentials come from `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` and `MOONSHOT_API_KEY` and are never written. The output directory must be outside the repository.

```sh
.venv/bin/python runner.py preflight --output ../out
.venv/bin/python runner.py run --study A --output ../out
.venv/bin/python verify.py --output ../out
.venv/bin/python runner.py run --study B --output ../out
.venv/bin/python verify.py --output ../out
```

Preflight sends 28 requests with input `Hello`: per model, the Study A shape without temperature and the Study B shape, plus the Study A shape with temperature 0 for the six models whose temperature is probed. A model passes when the Study B check passes and a Study A check passes; Study A uses temperature 0 when that check passes. A model that fails is OP in both studies. Runs require a complete preflight on the same commit, a clean working tree and `HEAD` at tag `v1.0.0`, or a descendant whose only difference is one added `DOI:` line in `PREREG.md`.

Four workers per vendor; vendors run in parallel. One spend cap of 400 USD covers preflight and both studies; the full worst-case envelope is larger (`protocol.json` `spend.cost_envelope_usd`). A completed response is never retried. Existing attempt output is never overwritten. Run status is COMPLETE, PAUSED or INCONCLUSIVE. PAUSED (spend cap, an introductory price past its end date, provider billing or quota response, or interrupt) resumes by repeating the same command. A first interrupt finishes in-flight requests and records PAUSED; a second exits at once, and the next run records the open attempts as abandoned. A returned model that differs from the requested model ends the study as INCONCLUSIVE.

## Output

```
out/preflight/{events.jsonl,completion.json,verdict.json}
out/preflight/attempts/<slot_id>/attempt-01/{request.bin,response.bin,classifier_input.bin,attempt.json,classification.json}
out/preflight/definitive/<slot_id>.json
out/study<A|B>/events.jsonl
out/study<A|B>/attempts/<slot_id>/attempt-<NN>/{request.bin,response.bin,classifier_input.bin,attempt.json,classification.json}
out/study<A|B>/definitive/<slot_id>.json
out/study<A|B>/completion.json
```

`response.bin` holds the vendor bytes unaltered; `classifier_input.bin` holds the extractor output that the upstream classifier reads; `classification.json` holds the final class, the upstream class and the extractor signals. `verify.py` recomputes the extraction and the classification from `response.bin`.

## Analysis

```sh
.venv/bin/python analysis.py --output ../out
```

Scores each prediction under the rules in `PREREG.md` from the verified receipts and prints the result as JSON.

## PA1 qualifying set

```sh
python3 qualifying.py /path/to/void-matrix-complete-analysis/analysis/tables/trial_level.csv
```

## License

MIT
