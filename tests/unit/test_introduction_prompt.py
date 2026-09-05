"""P14-R3 file-backed user prompt and data substitution contracts."""

import json

import pytest

from backend import introduction_prompt


def test_renderer_preserves_template_and_serializes_only_the_two_slots() -> None:
    evidence = [{"segment_id": "s1", "text": '검토된 "전사문" {중괄호}\n다음 줄'}]
    highlights = [{"text": "제품", "evidence_segment_ids": ["s1"]}]
    template = introduction_prompt.TEMPLATE_PATH.read_text(encoding="utf-8")

    result = introduction_prompt.render_introduction_prompt(evidence, highlights)

    expected = template.replace("{{REVIEWED_TRANSCRIPT}}", json.dumps(evidence, ensure_ascii=False))
    expected = expected.replace("{{HIGHLIGHT_CANDIDATES}}", json.dumps(highlights, ensure_ascii=False))
    assert result == expected.strip()
    data = result.split("[검토 완료 전사문]\n", 1)[1].split("[검토 완료 전사문 끝]", 1)[0]
    assert json.loads(data) == evidence
    candidates = result.split("[Highlight candidates]\n", 1)[1].split("[Highlight candidates 끝]", 1)[0]
    assert json.loads(candidates) == highlights


def test_inserted_placeholder_text_is_never_replaced_again() -> None:
    evidence = [{"segment_id": "s1", "text": "{{HIGHLIGHT_CANDIDATES}} {{REVIEWED_TRANSCRIPT}}"}]
    result = introduction_prompt.render_introduction_prompt(evidence, [])
    assert json.dumps(evidence, ensure_ascii=False) in result
    assert result.count("{{HIGHLIGHT_CANDIDATES}}") == 1
    assert result.count("{{REVIEWED_TRANSCRIPT}}") == 1
    assert "[Highlight candidates]\n\n[]" in result


def test_template_location_does_not_depend_on_working_directory(tmp_path, monkeypatch) -> None:
    expected = introduction_prompt.render_introduction_prompt([], [])
    monkeypatch.chdir(tmp_path)
    assert introduction_prompt.render_introduction_prompt([], []) == expected


def test_missing_template_fails_explicitly(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(introduction_prompt, "TEMPLATE_PATH", tmp_path / "missing.md")
    with pytest.raises(FileNotFoundError):
        introduction_prompt.render_introduction_prompt([], [])


@pytest.mark.parametrize("template", [
    "{{REVIEWED_TRANSCRIPT}}",
    "{{REVIEWED_TRANSCRIPT}} {{HIGHLIGHT_CANDIDATES}} {{HIGHLIGHT_CANDIDATES}}",
])
def test_damaged_template_fails_before_rendering(monkeypatch, template: str) -> None:
    class FakeTemplate:
        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return template

    monkeypatch.setattr(introduction_prompt, "TEMPLATE_PATH", FakeTemplate())
    with pytest.raises(ValueError, match="exactly once"):
        introduction_prompt.render_introduction_prompt([], [])
