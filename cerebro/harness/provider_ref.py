"""Provider-owned call correlation and replay state.

`ProviderCallRef` exists because there are two identities for one tool call and conflating them
loses correctness. `CerebroCallId` is what Cerebro executes, audits and recovers against.
`ProviderCallRef` is what the provider needs back in order to accept the next request.
"""

from __future__ import annotations

from pydantic import BaseModel, model_validator

__all__ = ["ProviderCallRef"]


class ProviderCallRef(BaseModel):
    """A provider-native correlation handle for one call.

    Losing a `replay_required` ref after the tool side effect has happened is a correctness
    failure, not a cosmetic one: the provider will refuse or misinterpret the continuation and
    the harness cannot legally re-run the effect to recover it.
    """

    model_config = {"frozen": True}

    provider_id: str
    native_call_id: str | None = None
    opaque: str | None = None
    replay_required: bool = False

    @model_validator(mode="after")
    def _needs_some_handle(self) -> "ProviderCallRef":
        if self.native_call_id is None and self.opaque is None:
            raise ValueError(
                "ProviderCallRef needs a native_call_id or an opaque handle; an empty ref "
                "cannot correlate anything"
            )
        if self.replay_required and not (self.native_call_id or self.opaque):
            raise ValueError("replay_required ProviderCallRef must carry a handle")
        return self
