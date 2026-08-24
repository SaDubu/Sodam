"""Local backend composition and pipeline-orchestration contract."""


def build_application() -> object:
    """Compose adapters and expose local job operations after dependencies exist.

    The finished implementation must sequence STT and Qwen execution, route
    failures through cleanup, and expose no cloud processing endpoint.
    """
    raise NotImplementedError("B13: build_application has not been implemented")
