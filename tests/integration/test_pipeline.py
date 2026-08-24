"""Skeleton integration tests for the sequential local pipeline; awaits B13."""
import pytest

pytestmark = pytest.mark.skip(reason="B13 is a declaration-only skeleton")


def test_pipeline_cleanup_paths_contract() -> None:
    """Plan: exercise success, failure, cancellation, and recovery via all fakes."""
    raise NotImplementedError
