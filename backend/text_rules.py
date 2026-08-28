"""Restricted rule normalization of protected text.

Applies four restricted whitespace/punctuation rules without changing
non-whitespace characters, placeholder values, or any other content.
"""

from __future__ import annotations

import re as _re

from .contracts import NormalizationError
from .contracts import ProtectedText
from .contracts import RuleNormalizedText

# Placeholder pattern: [[SODAM_PROTECTED_<digits>]]
_PH_KEY = _re.compile(r"\[\[SODAM_PROTECTED_\d+\]\]")

# Rule 3: punctuation characters whose preceding whitespace must be removed.
_PUNCT_CHARS_CLASS = ".!?:;,"

# Rule 4: bracket pairs (after open / before close).
_BRAKET_PAIRS = [
    ("(", ")"),
    ("[", "]"),
    ("{", "}"),
]

# Sentence boundary characters: . ! ?
_SENT_PUNCTUATION = ".!?"


def _validate_input(pt: ProtectedText) -> None:
    """Validate input to normalize_rules per SoF B08 §4 input contracts."""
    if not isinstance(pt, ProtectedText):
        raise TypeError("input must be a ProtectedText instance")

    text = pt.text
    repls = pt.replacements

    # text must be str
    if not isinstance(text, str):
        raise NormalizationError(
            "text must be str but got %r" % type(text).__name__
        )

    # replacements must be dict[str, str]
    if not isinstance(repls, dict):
        raise NormalizationError("replacements must be a dict")

    for key_ in repls:
        if not isinstance(key_, str) or not _PH_KEY.fullmatch(key_):
            raise NormalizationError(
                "placeholder key must be a valid placeholder (e.g. [[SODAM_PROTECTED_0001]]) "
                "but got %r" % (key_ if isinstance(key_, str) else type(key_).__name__)
            )
        val_ = repls[key_]
        if not isinstance(val_, str):
            raise NormalizationError("value of key %r must be str" % (key_,))

    # Each map key must appear exactly once in text.
    for key_ in list(repls.keys()):
        n_text = text.count(key_)
        if n_text == 0:
            raise NormalizationError("key %r not found in text" % (key_,))
        if n_text != 1:
            raise NormalizationError(
                "key %r appears %d times (expected exactly one)"
                % (key_, n_text)
            )

    # All placeholder tokens in input text must be known keys.
    placeholders_in_text = _re.findall(_PH_KEY, text)
    unknown_keys = [p for p in placeholders_in_text if p not in repls]
    if unknown_keys:
        raise NormalizationError("unknown placeholders: %r" % (unknown_keys,))


def normalize_rules(protected_text: ProtectedText) -> RuleNormalizedText:
    r"""Apply four restricted normalization rules.

    Returns a new :class:`RuleNormalizedText` with sentence boundaries.
    """
    _validate_input(protected_text)

    text = protected_text.text
    replacements = protected_text.replacements

    # ------------------------------------------------------------------ #
    # Rule 1: collapse all whitespace sequences to single U+0020 space.   #
    # ------------------------------------------------------------------ #
    text = _re.sub(r"\s+", " ", text)

    # ------------------------------------------------------------------ #
    # Rule 2: strip leading and trailing whitespace from result.         #
    # ------------------------------------------------------------------ #
    text = text.strip()

    # ------------------------------------------------------------------ #
    # Rule 3: remove space immediately before punctuation chars .!?:;,   #
    # ------------------------------------------------------------------ #
    rule3_pat = r"\s+([" + _PUNCT_CHARS_CLASS + r"])"
    text = _re.sub(rule3_pat, lambda m: m.group(1), text)

    # ------------------------------------------------------------------ #
    # Rule 4: remove whitespace after open bracket and before close.     #
    # ------------------------------------------------------------------ #
    for open_ch, close_ch in _BRAKET_PAIRS:
        esc_open = _re.escape(open_ch)
        esc_close = _re.escape(close_ch)
        # After open bracket: "( text" -> "(text"
        rule4a_after = "({})\\s+".format(esc_open)
        text = _re.sub(rule4a_after, lambda m: open_ch, text)
        # Before close bracket: "text )" -> "text)"
        rule4b_before = r"\s+({})".format(esc_close)
        text = _re.sub(rule4b_before, lambda m: close_ch, text)

    # ------------------------------------------------------------------ #
    # Non-whitespace invariant (SoF §4 unvariant):                       #
    # removing whitespace from input and output must yield identical      #
    # string. If violated → NormalizationError.                          #
    # ------------------------------------------------------------------ #
    orig_nonspace = "".join(ch for ch in protected_text.text if not ch.isspace())
    norm_nonspace = "".join(ch for ch in text if not ch.isspace())
    if orig_nonspace != norm_nonspace:
        raise NormalizationError(
            "non-whitespace sequence changed during normalization"
        )

    # ------------------------------------------------------------------ #
    # Placeholder presence post-normalization: known keys must appear     #
    # exactly once; all placeholder tokens must be known keys.           #
    # ------------------------------------------------------------------ #
    placeholders_in_result = _re.findall(_PH_KEY, text)

    # All known keys must appear exactly once
    for key_ in replacements:
        if text.count(key_) != 1:
            raise NormalizationError(
                "placeholder %r must appear exactly once in result (found %d)"
                % (key_, text.count(key_))
            )

    # All tokens in result must be known keys
    for p_token in placeholders_in_result:
        if p_token not in replacements:
            raise NormalizationError(
                "unknown placeholder in result: %r" % (p_token,)
            )

    # ------------------------------------------------------------------ #
    # Compute sentence boundaries per SoF §4:                             #
    # indices right after . ! ? where the next character is a space      #
    # or end of string. 0-based slice-end index.                          #
    # ------------------------------------------------------------------ #
    sentence_boundaries = []
    for i, ch in enumerate(text):
        if ch in _SENT_PUNCTUATION:
            boundary_end = i + 1
            if boundary_end == len(text) or text[boundary_end] == " ":
                sentence_boundaries.append(boundary_end)

    return RuleNormalizedText(
        text=text,
        sentence_boundaries=tuple(sentence_boundaries),
    )
