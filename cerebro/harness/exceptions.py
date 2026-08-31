"""Harness v1 exception types.

These are deliberately loud. A Harness invariant that fails quietly is the failure mode the whole
design exists to prevent, so every one of these is raised rather than logged.
"""

from __future__ import annotations

__all__ = [
    "ContinuationNotAdmissible",
    "DuplicateHarnessIdentity",
    "HarnessError",
    "HarnessRecordNotFound",
    "HarnessStateError",
    "StaleHarnessWrite",
    "UnknownDialect",
    "UnsupportedDialectFeature",
    "UnsupportedFormatVersion",
]


class HarnessError(Exception):
    """Base class for Harness contract violations."""


class HarnessStateError(HarnessError):
    """A durable state transition was requested that the contract forbids.

    Raised for backwards transitions and for dispatch preconditions that are not met. Monotonic
    progress is the property recovery depends on; a silently ignored illegal transition is
    indistinguishable from a successful one afterwards.
    """


class StaleHarnessWrite(HarnessStateError):
    """A compare-and-set write named a version that is no longer current."""


class DuplicateHarnessIdentity(HarnessStateError):
    """An identity was reused for different durable Harness state."""


class HarnessRecordNotFound(HarnessStateError):
    """A requested durable Harness identity does not exist."""


class UnsupportedFormatVersion(HarnessError):
    """A serialized object declares a `format_version` this build cannot read."""

    def __init__(self, kind: str, version: object, supported: object) -> None:
        self.kind = kind
        self.version = version
        self.supported = supported
        super().__init__(
            f"{kind} format_version {version!r} is not supported by this build "
            f"(supported: {sorted(supported)!r})"
        )


class UnsupportedDialectFeature(HarnessError):
    """The canonical request contains something this provider dialect cannot express.

    Explicit refusal, never silent omission: a dialect that drops what it cannot encode produces
    a request the model answers confidently and wrongly.
    """


class UnknownDialect(HarnessError):
    """No adapter is registered for the requested dialect."""


class ContinuationNotAdmissible(HarnessError):
    """A provider/model combination cannot be admitted under AR-11.

    Raised when required continuation state cannot be represented losslessly in durable ordered
    items, refs and opaque replay material. Generic harness code does not invent a replay
    strategy in that case.
    """
