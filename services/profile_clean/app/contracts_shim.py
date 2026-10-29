"""Local fallback if biflow-contracts is not installed (use real package in production)."""
try:
    from biflow_contracts import *  # noqa: F403
    from biflow_contracts.models import *  # noqa: F403
except ImportError as e:
    raise ImportError("Install biflow-contracts: pip install -e ../../contracts") from e
