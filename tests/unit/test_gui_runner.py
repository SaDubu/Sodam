"""P15 bridge test contracts; placeholders are skipped, not passing tests."""

import pytest

from tests.fakes_gui import FakePipe, FakeProcess, FakeProcessFactory

def test_process_fakes_contract() -> None:
    """H01: bytes/EOF/partial reads/close/faults, poll/wait and recorded argv.

    Boundary read(0), empty pipe, nonzero exit; reject bad types/sizes. No OS child.
    """
    stdout = FakePipe((b"abc", b"def"))
    assert stdout.read(2) == b"ab"
    assert stdout.read(10) == b"cdef"
    assert stdout.read() == b""
    assert stdout.read(0) == b""
    stdout.close()
    assert stdout.close_calls == 1
    with pytest.raises(ValueError):
        stdout.read()

    failure = FakePipe((b"x",), OSError("read failed"))
    assert failure.read() == b"x"
    with pytest.raises(OSError, match="read failed"):
        failure.read()
    assert failure.read() == b""

    process = FakeProcess(stdout=FakePipe(()), stderr=FakePipe(()), exit_code=1)
    assert process.poll() is None
    assert process.wait() == 1
    assert process.poll() == 1
    assert process.wait_calls == [None]
    with pytest.raises(ValueError):
        process.wait(-1)

    factory = FakeProcessFactory(process)
    assert factory(["python", "runner"], shell=False) is process
    assert factory.calls == [((["python", "runner"],), {"shell": False})]
    failing_factory = FakeProcessFactory(process, OSError("launch failed"))
    with pytest.raises(OSError, match="launch failed"):
        failing_factory("argv")


@pytest.mark.skip(reason="P15 scaffold: awaiting implementation")
def test_report_and_event_fixtures_contract() -> None:
    """H03: all modes/scenarios, independent results, unknown scenario ValueError.

    Use tmp_path and existing ProgressEvent; no real media or model is required.
    """
    raise NotImplementedError("P15-TH03")


@pytest.mark.skip(reason="P15 scaffold: awaiting implementation")
def test_normalize_source_contract() -> None:
    """F01: URL/local/quoted Korean path; reject empty/relative/UNC/Markdown.

    tmp_path and path fakes cover directory/missing/symlink. Assert exact source,
    TypeError/ValueError/InputSourceError, unchanged media and zero network calls.
    """
    raise NotImplementedError("P15-T01")


@pytest.mark.skip(reason="P15 scaffold: awaiting implementation")
def test_build_runner_argv_contract() -> None:
    """F02: all modes and overrides, URL-only allow-url, source is one final arg.

    Reject bad types/modes/missing runtimes; stat fixtures only, no process launch.
    """
    raise NotImplementedError("P15-T02")


@pytest.mark.skip(reason="P15 scaffold: awaiting implementation")
def test_event_buffer_contract() -> None:
    """F03: empty/burst/concurrent publish/drain, first-stage percent retained.

    Tiny diagnostic cap, terminal retention, invalid event/limit no mutation;
    assert bounded memory/delivery and isolated fresh-run buffers, no Tk needed.
    """
    raise NotImplementedError("P15-T03")


@pytest.mark.skip(reason="P15 scaffold: awaiting implementation")
def test_parse_stderr_line_contract() -> None:
    """F04: real JSONL, plain error/candidate, empty/bad/oversized JSON, bad types.

    Only schema-valid progress is trusted; text is preserved within byte budget.
    """
    raise NotImplementedError("P15-T04")


@pytest.mark.skip(reason="P15 scaffold: awaiting implementation")
def test_parse_runner_report_contract() -> None:
    """F05: modes/fallback/reviews, exit1, malformed/multiple JSON, missing fields.

    Inject tmp_path root; reject traversal, symlink, missing or mismatched job
    folder and truncated report. No raw traceback and no filesystem writes.
    """
    raise NotImplementedError("P15-T05")


@pytest.mark.skip(reason="P15 scaffold: awaiting implementation")
def test_stream_process_contract() -> None:
    """F06: FakeProcess success/start/read failures, invalid UTF-8, output limits.

    Add bounded handshake byte streams to prove both pipes drain concurrently;
    assert shell=False, hidden console, child-only environment, full drain after
    overflow, pipe close/reader join/reap before exited and no Tk calls.
    """
    raise NotImplementedError("P15-T06")
