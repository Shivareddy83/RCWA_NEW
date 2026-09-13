class ReconciliationError(Exception):
    """Base exception for deterministic reconciliation failures."""


class AmbiguousMatchError(ReconciliationError):
    """Raised only when a matching rule produces multiple candidates."""
