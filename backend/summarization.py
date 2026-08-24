"""Evidence-linked, maximum-two-sentence summarization contract."""

from .contracts import Summary, Transcript


def summarize_transcript(transcript: Transcript) -> Summary:
    """Produce an evidence-linked Korean summary with at most two sentences.

    The implementation will use bounded hierarchical local-model calls and must
    reject empty transcripts, unsupported output, and claims without evidence.
    """
    raise NotImplementedError("B12: summarize_transcript has not been implemented")
