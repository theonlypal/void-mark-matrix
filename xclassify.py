"""Cross-provider classification entrypoint, version void-mark-xprovider-1. No network operations.

classifier.py is the upstream classifier, byte-identical to the source repository. This module calls it on the
extractor output unchanged and keeps its result as upstream_class. For a successful model completion, extractor
signals the upstream classifier has no field for then set the final class, in this order:

  unknown output part                      -> PI  (structural incompatibility; non-Void)
  provider safety block                    -> SB  (non-Void; never RF)
  upstream RF or TC                        -> kept
  tool termination without a tool payload  -> PI  (non-Void; not TC)
  non-final continuation                   -> CN  (non-Void; not a normal-stop Void)

Every other result is the upstream result. For a valid Anthropic Messages response with known block types, the final
class equals the upstream class.
"""
import classifier
import vendors

VERSION = "void-mark-xprovider-1"
EXTENSION_CLASSES = {"CN": "Successful provider response ending in a non-final continuation state; no continuation request is sent"}
CLASSES = {e: classes + list(EXTENSION_CLASSES) for e, classes in classifier.CLASSES.items()}
RULES = [
    ["unknown_parts", "PI", "unknown output part"],
    ["safety_block", "SB", "provider safety block"],
    ["upstream RF or TC", None, "kept"],
    ["tool_termination_without_payload", "PI", "tool termination without a tool payload"],
    ["continuation", "CN", "non-final continuation"],
]


def final_class(upstream, signals):
    if signals["unknown_parts"]:
        return "PI", "unknown output part: " + "; ".join(signals["unknown_parts"])
    if signals["safety_block"]:
        return "SB", "provider safety block: " + signals["safety_block"]
    if upstream in ("RF", "TC"):
        return upstream, None
    if signals["tool_termination_without_payload"]:
        return "PI", "tool termination without a tool payload: " + signals["tool_termination_without_payload"]
    if signals["continuation"]:
        return "CN", "non-final continuation"
    return upstream, None


def classify_attempt(experiment, vendor, http_status, raw):
    """Classifier input bytes and the classification of one attempt."""
    mapped, signals = vendors.extract(vendor, http_status, raw)
    result = classifier.classify(experiment, http_status, mapped)
    upstream = result["class"]
    final, reason = final_class(upstream, signals) if result["model_completion"] else (upstream, None)
    result.update({"classification_version": VERSION, "upstream_class": upstream, "class": final,
                   "void": final in classifier.VOID_CLASSES, "extension_reason": reason, "signals": signals})
    return mapped, result
