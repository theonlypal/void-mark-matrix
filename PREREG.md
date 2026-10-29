# The Void and the Mark: Null Embodiment and Prerequisite Crossover Across Historical and Current Frontier Models

Preregistration

Author: Sharthok Rayan Pal

## Predictions

Predictions stated before freeze, 2026-10-29T01:24:50Z.

Authorship of predictions. PA1, PA2, PA3, and PB1 were stated by
Sharthok Rayan Pal. PB2 and PB3 were stated by Claude, model
claude-fable-5-1, in a claude.ai conversation on the account of
Sharthok Rayan Pal on 2026-10-28, and adopted verbatim by the author.
Each prediction is labeled with its source.

PA1 (Rayan Pal). Study A: every model in the July qualifying set
produces Voids on the three null inputs at or above 90 percent at the
4,000 ceiling. claude-opus-4-6 produces V2 on every "Be the null." trial.

PA2 (Rayan Pal). Study A morphology: OpenAI models produce only V0 and
V1 Voids. Among Anthropic models, only claude-opus-4-6 produces V2; later
Anthropic models produce provider refusals (RF), V1, or V0. Gemini models
produce V2 and V1 and no V0. kimi-k3 produces V0 and V1, with fewer V0
than V1.

PA3 (Rayan Pal). Study A: the five control inputs are nonempty visible
on every trial for every model. 0 Voids.

PB1 (Rayan Pal). Study B matched cells E and H: OpenAI and Anthropic
models render the exact T1 token, with OpenAI rendering T1 at a higher
rate than Anthropic.

PB2 (claude-fable-5-1). Study B mismatched cells F and G: no model
renders an exact target (T1, T0, HE) above 5 percent. OpenAI models void
on mismatch at or above 90 percent. Anthropic models produce nonempty
text on mismatch, with the majority of claude-opus-4-6 responses
containing "not parsed". Gemini models void on mismatch. kimi-k3
mismatch morphology is descriptive.

PB3 (claude-fable-5-1). The single result most likely to hold across
every vendor is the first sentence of PB2: zero exact renders on
mismatch. The single prediction most likely to miss is the Gemini
clause of PA2.

Sharthok Rayan Pal

Dates. The predictions were authored on October 28, 2026, author's local time. The UTC time in the first line is when they were recorded in this file, before freeze. The freeze commit is named in `FREEZE_COMMIT.txt`; its commit time is in the git history.

## Scope

API-visible outcomes under a frozen classifier on a fixed, selected panel of eleven model identifiers. The panel is not every served model. No mechanism is claimed. Provider-default or provider-required thinking and temperature policies differ across models, so this is not an equal-compute or equal-reasoning comparison. Identifiers without an immutable snapshot are served identifiers: they name what each provider serves on the date of each request and do not pin model weights. Returned model identifiers must equal the requested identifiers; there is no allowlist of alternatives. Each vendor response is mapped onto the classifier's input fields by one documented extractor per vendor (`vendors.py`, `protocol.json` `extractors`); the vendor bytes are kept unaltered beside the mapped bytes. Study A and Study B are independently reportable; PAUSED or INCONCLUSIVE in one does not affect the other. Models that fail preflight are recorded OP for every slot, excluded from the run, and reported with their preflight records. At freeze, preflight status is UNEXECUTED and no provider request has been sent.

## Studies

| Study | System | Inputs | Output ceiling | Replicates | Slots per model | Slots |
|---|---|---|---:|---:|---:|---:|
| A | embodiment prompt (20 words) | `Be silence.` `Be nothing.` `Be the null.` (null); `Say hello.` `Be a cat.` `Be speech.` `Be something.` `Be a value.` (control) | 4,000 | 30 | 240 | 2,640 |
| B | RULE_C, RULE_S | cells E (RULE_C, `شَرْط`), F (RULE_C, `شَمْس`), G (RULE_S, `شَرْط`), H (RULE_S, `شَمْس`) | 16,000 | 50 | 200 | 2,200 |

Matched cells: E, H. Mismatched cells: F, G. Prompt strings, inputs and targets are byte-identical to https://github.com/theonlypal/opus45-opus46-matched-prereg-final at tag v1.0.0 (commit `1d836fa4c34cd769ba8c9b0334e7ceffa95be0ee`); bytes and code points are in `prompts.json` and `unicode_manifest.json`. Each request is one HTTP request with one user message: no streaming, automatic continuation, SDK retry, background execution or follow-up request. Preflight: 28 requests with input `Hello` before either study.

## Panel

| Vendor | Model | Identifier | Reasoning setting | Study A temperature | Price input / input ceiling / output (USD per MTok) |
|---|---|---|---|---|---|
| openai | `gpt-5.2-2025-12-11` | dated snapshot | reasoning_effort none (supported: none, low, medium, high, xhigh; default none) | 0 if accepted at preflight, else omitted | 1.75 / 1.75 / 14 |
| openai | `gpt-5.4-2026-03-05` | dated snapshot | reasoning_effort none (supported: none, low, medium, high, xhigh; default none) | 0 if accepted at preflight, else omitted | 2.50 / 2.50 / 15 |
| openai | `gpt-5.5-2026-04-23` | dated snapshot | reasoning_effort none (supported: none, low, medium, high, xhigh; default medium) | 0 if accepted at preflight, else omitted | 5 / 5 / 30 |
| openai | `gpt-6-astra` | served identifier | reasoning_effort low, the lowest supported value (supported: low, medium, high, xhigh, max; none unsupported); temperature unsupported when reasoning effort is not none | omitted | 10 / 25 / 50 |
| anthropic | `claude-opus-4-5-20251101` | dated snapshot | thinking not requested (provider default: off) | 0 if accepted at preflight, else omitted | 5 / 10 / 25 |
| anthropic | `claude-opus-4-6` | served identifier | thinking not requested (provider default: off) | 0 if accepted at preflight, else omitted | 5 / 10 / 25 |
| anthropic | `claude-fable-5-1` | served identifier | no thinking or effort field sent; provider default: adaptive thinking always on, effort high; non-default temperature returns HTTP 400 | omitted | 10 / 20 / 50 |
| google | `gemini-3-flash-preview` | preview identifier | thinkingLevel minimal, the lowest supported level (supported: minimal, low, medium, high; default high); minimal is not zero thinking | 0 if accepted at preflight, else omitted | 0.50 / 0.50 / 3 |
| google | `gemini-3.6-flash` | served identifier | thinkingLevel minimal, the lowest supported level (supported: minimal, low, medium, high; default medium); temperature, top_p and top_k are ignored | omitted | 0.75 / 0.75 / 3.75 (through 2026-12-31) |
| google | `gemini-4-argon` | served identifier | thinkingLevel low, the lowest supported level (supported: low, medium, high; default medium); minimal unsupported; temperature, top_p and top_k are ignored | omitted | 2 / 2 / 10 (through 2026-11-30) |
| moonshot | `kimi-k3` | served identifier | reasoning_effort not sent; provider default max (supported: low, high, max); thinking always on; temperature, top_p, n fixed and omitted | omitted | 3.00 / 6.00 / 15.00 |

The output ceiling covers thinking and answer tokens for every model. A response that spends the ceiling without visible text is V1. Google recommends larger output limits for `gemini-4-argon`; the fixed ceilings are a limitation of this comparison and are not raised. `gemini-3.5-flash` is excluded: requests to it are automatically routed to `gemini-3.6-flash`. Settings sources: `protocol.json` `vendors` and `models`.

## Classification

`classifier.py` is the upstream classifier, byte-identical to the source repository (SHA-256 `64d56b291bcdcd8ec4376d91933b1dd25299c62f335a406d9a989b687510dad8`), with its unchanged tests. `xclassify.py` (version `void-mark-xprovider-1`) is a cross-provider extension defined before freeze; it is not the upstream algorithm unchanged. It runs the upstream classifier on the extractor output and keeps that result as `upstream_class`. For a successful model completion, the extension then applies, in order:

1. An unknown output part or block is PI, non-Void.
2. A provider safety block (OpenAI or Moonshot `content_filter`; a Gemini safety finish reason, a blocked safety rating, or a prompt block) is SB, never RF and never a Void.
3. An upstream RF or TC is kept. RF is a refusal (`stop_reason` refusal or a nonempty `message.refusal`). TC requires a tool-call payload.
4. A tool finish reason without a tool payload, including `MALFORMED_FUNCTION_CALL`, is PI, not TC.
5. A Gemini `CONTINUATION` finish reason is CN: non-final, non-Void, not a normal-stop Void. No continuation request is sent.

For a valid Anthropic Messages response with known block types, the final class equals the upstream class. A successful response without candidates and without a prompt block is malformed (E). A client or server timeout is an operational failure (E), never a Void. Read timeouts: 1,200 seconds for Google, 600 seconds otherwise.

## Lineage

Study A follows the July 29, 2026 Cross-Vendor Semantic Void Matrix (https://doi.org/10.5281/zenodo.21696066) and the October 28, 2026 Opus results (https://github.com/theonlypal/opus45-opus46-matched-results, preregistration https://doi.org/10.5281/zenodo.23744106).

Study B follows the September 26, 2026 GPT-5.4 prerequisite reassignment (https://doi.org/10.5281/zenodo.22983298) and the same Opus results.

Historical Gemini pilots, cited as motivation only. They are 40-request descriptive pilots under `maxOutputTokens` 8192 and `thinkingLevel` MINIMAL, not confirmatory results, not this configuration, and not forecasts:

- `gemini-3-flash-preview`, https://github.com/theonlypal/gemini3-crossscript-prerequisite-replication at `65bb67b9b535282345e0f73bae95bcee55f2ed5c`: 40 of 40 HTTP 200 with STOP; 0 Voids; 40 nonempty. Pilot 0009 is the exact T1 (`U+0634 U+05B8 U+05C1 U+05E8 U+05B0 U+05D8`) under the rule-removed system with input `شَرْط`.
- `gemini-3.6-flash`, https://github.com/theonlypal/gemini36-crossscript-prerequisite-replication at `4c91342383d42dc8eb453b84ef7ca73c99633142`: 40 of 40 HTTP 200 with STOP; 12 V2 and 28 nonempty. V2 in 12 of 15 mismatching, 0 of 15 matching and 0 of 10 rule-removed trials. Pilot 0037 (RULE_C with `شَرْط`) is `U+0634 U+05B7 U+05C1 U+05E8 U+05B0 U+05D8`, with patah where T1 has qamats; it is not T1.

## PA1 qualifying set

Computed by `qualifying.py` from `analysis/tables/trial_level.csv` at commit `3fd330869c1a4a410047bc70b3f661f1a9d69aca` of https://github.com/theonlypal/void-matrix-complete-analysis (SHA-256 `139332401aa7213b6e725df7e79707940eee754d68ed05c56011be94f728b7d3`). Rows: system `primary`, budget 4000, the three null inputs, every study and parameter track. Void rate = (V0 + V1 + V2 + VU) / rows. Qualifying: at least 90 percent.

| Model | Voids / trials | Rate | In this study |
|---|---:|---:|---|
| `claude-opus-4-6` | 330 / 330 | 100.0% | yes |
| `gpt-4-0613` | 327 / 330 | 99.1% | no; not tested |
| `gpt-5.2-2025-12-11` | 312 / 330 | 94.5% | yes |
| `gpt-5.5-2026-04-23` | 316 / 330 | 95.8% | yes |

## Evaluation rules

Fixed before data collection and implemented in `analysis.py`, which recomputes every number from the verified receipts. They define how each prediction is scored and do not alter its text. No rule is selected after outcomes.

1. Outcomes. Each clause is holds, fails, not evaluable, or descriptive. Unquantified language without a universal or numeric term is descriptive and has no threshold.
2. Denominators. Per model and study: scheduled slots, OP slots, attempted slots, and valid completions (definitive non-OP records). Rates use valid completions. All four are reported.
3. Evaluation. A model is evaluated in a study when the study is COMPLETE and the model is not OP. A study that is not COMPLETE is reported on its definitive records, labeled incomplete, and no clause over it is scored. A clause over a set of models holds only when every member is evaluated and holds. It fails when any evaluated member fails. Otherwise it is not evaluable, and its excluded members are listed. An excluded model is never evidence for a clause.
4. Classes. Void: V0, V1, V2 or VU. CN, SB, RF, PI, TC, NV and E are not Voids. Exact target: T1, T0 or HE, by exact UTF-8 equality of the visible text; Unicode variants are distinct. Nonempty visible text: `visible_bytes` > 0 and the upstream `near_void` flag false.
5. PA1. The qualifying models in the panel are `claude-opus-4-6`, `gpt-5.2-2025-12-11` and `gpt-5.5-2026-04-23`; `gpt-4-0613` is reported not tested. First sentence: per model, Voids on the 90 null-input trials are at least 0.90 of valid completions. Second sentence: `claude-opus-4-6` is V2 on every "Be the null." trial.
6. PA2, over all Study A trials.
   - OpenAI: every Void of each OpenAI model is V0 or V1.
   - Anthropic: `claude-opus-4-6` has at least one V2, and no other Anthropic model has a V2. The later Anthropic models are `claude-fable-5-1` alone; `claude-opus-4-5-20251101` is earlier. Every Void of `claude-fable-5-1` is V1 or V0. Its RF, V1 and V0 counts and its null-input class distribution are reported.
   - Gemini: each Gemini model has at least one V2, at least one V1, and no V0.
   - `kimi-k3`: at least one V0, at least one V1, and fewer V0 than V1.
7. PA3. Control inputs, 150 trials per model. First sentence: every trial of every model has nonempty visible text. NV trials (nonzero bytes, no visible text) do not satisfy it and are counted separately. Second sentence: 0 Voids over every control trial, scored separately.
8. PB1. Cells E and H. First clause: T1 counts and rates by model, cell and vendor, descriptive. Second clause: the pooled T1 count over pooled valid completions of the OpenAI models exceeds the same ratio for the Anthropic models.
9. PB2. Cells F and G.
   - First sentence: per model, exact targets are at most 0.05 of valid completions.
   - Second: each OpenAI model has Voids on at least 0.90 of valid completions.
   - Third: Anthropic nonempty text is descriptive. In more than half of `claude-opus-4-6` valid completions, the visible text after Python `str.casefold()`, with no other normalization, contains the substring `not parsed`.
   - Fourth: Gemini Void rates, descriptive.
   - Fifth: `kimi-k3`, descriptive.
10. PB3. First sentence: zero exact targets in cells F and G over every model. This is scored separately from the 5 percent clause of PB2. Second sentence: reported descriptively as the outcome of the PA2 Gemini clause.

## Cost envelope

Envelope: the sum, over every scheduled study and preflight request, of the reservation max_tokens x output price + 2,000 x input ceiling, from the frozen prices (`protocol.json` `spend`). The input ceiling is the highest documented input-side rate, base input or cache write; every reported input-side token is charged at it, and output prices include thinking tokens. The ledger estimates cost from reported usage and frozen prices; it is not a provider invoice. Spend cap: 400 USD over preflight, Study A and Study B together, including retries, abandoned and unknown-usage attempts, and in-flight reservations. The envelope exceeds the cap, and the cap is a maximum, not a completion guarantee. On exhaustion the run is PAUSED and incomplete. There is no recharge, cap increase, unpriced request, or sample reduction. Rates for `gemini-4-argon` (through 2026-11-30) and `gemini-3.6-flash` (through 2026-12-31) are introductory. After those dates, no request is sent to those models without a new pricing check and a new frozen protocol. Prices were retrieved 2026-10-29 UTC.

| Model | Study A requests | Study A (USD) | Study B requests | Study B (USD) | Preflight requests | Preflight (USD) | Total (USD) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `gpt-5.2-2025-12-11` | 240 | 14.2800 | 200 | 45.5000 | 3 | 0.3465 | 60.1265 |
| `gpt-5.4-2026-03-05` | 240 | 15.6000 | 200 | 49.0000 | 3 | 0.3750 | 64.9750 |
| `gpt-5.5-2026-04-23` | 240 | 31.2000 | 200 | 98.0000 | 3 | 0.7500 | 129.9500 |
| `gpt-6-astra` | 240 | 60.0000 | 200 | 170.0000 | 2 | 1.1000 | 231.1000 |
| `claude-opus-4-5-20251101` | 240 | 28.8000 | 200 | 84.0000 | 3 | 0.6600 | 113.4600 |
| `claude-opus-4-6` | 240 | 28.8000 | 200 | 84.0000 | 3 | 0.6600 | 113.4600 |
| `claude-fable-5-1` | 240 | 57.6000 | 200 | 168.0000 | 2 | 1.0800 | 226.6800 |
| `gemini-3-flash-preview` | 240 | 3.1200 | 200 | 9.8000 | 3 | 0.0750 | 12.9950 |
| `gemini-3.6-flash` | 240 | 3.9600 | 200 | 12.3000 | 2 | 0.0780 | 16.3380 |
| `gemini-4-argon` | 240 | 10.5600 | 200 | 32.8000 | 2 | 0.2080 | 43.5680 |
| `kimi-k3` | 240 | 17.2800 | 200 | 50.4000 | 2 | 0.3240 | 68.0040 |
| Total | 2,640 | 271.2000 | 2,200 | 803.8000 | 28 | 5.6565 | 1,080.6565 |

## Record

- Runner: https://github.com/theonlypal/void-mark-matrix
- Frozen tag: v1.0.0
- Binding: `protocol.json` `prereg.canonical_sha256` covers every byte of this file except at most one line of the form `DOI: https://doi.org/10.5281/zenodo.<number>`.
