"""P08 test-contract skeleton for installed desktop backend discovery.

These tests intentionally remain skipped until P08-01 exposes a testable
resolver or an equivalent desktop command seam. They document the fixture,
inputs, and acceptance criteria without exercising an installed application.
"""

from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.skip(
    reason="P08-01 backend layout resolver is a declared skeleton, not implemented"
)


def test_packaged_resource_layout_is_selected_without_repository_cwd(
    tmp_path: Path,
) -> None:
    """A fixture resource root with backend/ and tools/run_local.py must win.

    The implemented test will launch the resolver with an unrelated current
    working directory and assert that doctor reports backend_resource_ready.
    """
    raise NotImplementedError("P08-01 resolver fixture pending")


def test_missing_packaged_runner_is_a_packaging_error(tmp_path: Path) -> None:
    """A partial resource tree must not be reported as a runtime-path problem."""
    raise NotImplementedError("P08-01 resolver fixture pending")
