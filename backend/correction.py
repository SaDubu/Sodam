"""Constrained local-LLM correction contracts."""

from .contracts import CorrectionResult, RuleNormalizedText


def correct_chunk(text: RuleNormalizedText, context: tuple[str, ...]) -> CorrectionResult:
    """Request and validate JSON-only correction for a bounded adjacent chunk.

    A future implementation must use an injected local runtime, reject excessive
    input and invalid JSON, and never accept unclassified changes silently.
    """
    raise NotImplementedError("B09: correct_chunk has not been implemented")
