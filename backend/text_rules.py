"""Restricted spacing, punctuation, and sentence-boundary contracts."""

from .contracts import ProtectedText, RuleNormalizedText


def normalize_rules(protected_text: ProtectedText) -> RuleNormalizedText:
    """Normalize only permitted whitespace and obvious punctuation noise.

    Future logic must preserve all protected placeholders and all non-whitespace
    Korean, Latin, and numeric characters, or raise an invariant error.
    """
    raise NotImplementedError("B08: normalize_rules has not been implemented")
