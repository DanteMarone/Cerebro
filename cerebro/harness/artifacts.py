"""Harness-owned durable storage for complete raw tool output (section 18).

Raw output is evidence. It is what proves what a tool actually returned when the model-visible
projection is bounded, and it is the only thing an operator can look at when a call has to be
reconciled by hand. It therefore never goes into `messages`, Hub events or the legacy
`tool_calls` table: those are product surfaces with their own retention and their own audiences.

**Policy, decided here because this is the code that creates the data (AR-12).**

- *Backend*: `harness_artifacts` rows in the Harness database, plus a Harness-owned directory
  under the configured data directory for anything past the inline threshold. Nothing else
  writes to that directory.
- *Inline threshold*: `INLINE_THRESHOLD_BYTES` (8 KiB of UTF-8). At or below it the exact bytes
  live in the row, so the common case needs no file at all. Above it the bytes live in one file
  named by the artifact reference.
- *Durability*: the file is written to a temporary name, flushed, `fsync`-ed and then atomically
  renamed **before** the semantic transaction starts. The index row is inserted inside that
  transaction. A committed `ArtifactRef` therefore always points at a complete object, and a
  rolled-back transaction leaves at most an unreferenced file that nothing can name.
- *Retention*: `conversation` — an artifact lives as long as the turn that produced it. Nothing
  in Phase 1C prunes automatically; deletion is an explicit operator action, because deleting
  the evidence for an unreconciled effect is worse than keeping it.
- *Provenance*: every row records the producing turn, call, tool key, binding generation, exact
  byte size and SHA-256 of the stored bytes.
- *Access and redaction*: the payload is readable only through `ArtifactStore.read`. It is never
  logged, never published to the Hub and never placed in a model-visible projection. Generic
  surfaces get `describe()`, which carries size and digest and no content.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cerebro.harness.exceptions import HarnessRecordNotFound, HarnessStateError
from cerebro.harness.ids import AgentTurnId, ArtifactRef, CerebroCallId, ToolBindingGeneration
from cerebro.harness.tooling import ToolKey

__all__ = [
    "ARTIFACT_FORMAT_VERSION",
    "ARTIFACT_RETENTION_POLICY",
    "INLINE_THRESHOLD_BYTES",
    "ArtifactStore",
    "StagedArtifact",
    "StoredArtifact",
]

ARTIFACT_FORMAT_VERSION = 1
INLINE_THRESHOLD_BYTES = 8 * 1024
ARTIFACT_RETENTION_POLICY = "conversation"

_ARTIFACT_DIRNAME = "harness_artifacts"


@dataclass(frozen=True)
class StagedArtifact:
    """Raw output that is already durable but not yet referenced by any committed row.

    Staging is the whole trick behind "a committed `ArtifactRef` cannot dangle": the bytes are
    on disk before the semantic transaction opens, and the reference only becomes reachable if
    that transaction commits.
    """

    artifact_ref: ArtifactRef
    agent_turn_id: AgentTurnId
    call_id: CerebroCallId
    tool_key: ToolKey
    binding_generation: ToolBindingGeneration
    content_type: str
    storage_backend: str
    byte_size: int
    content_sha256: str
    inline_payload: str | None
    relative_path: str | None
    retention_policy: str
    provenance: dict[str, Any]
    created_at: str

    def insert_values(self) -> tuple[Any, ...]:
        """Row values in `harness_artifacts` column order."""
        from cerebro.harness.serialization import canonical_json

        return (
            str(self.artifact_ref),
            ARTIFACT_FORMAT_VERSION,
            str(self.agent_turn_id),
            str(self.call_id),
            self.tool_key.canonical(),
            str(self.binding_generation),
            self.content_type,
            self.storage_backend,
            self.byte_size,
            self.content_sha256,
            self.inline_payload,
            self.relative_path,
            self.retention_policy,
            canonical_json(self.provenance),
            self.created_at,
        )


@dataclass(frozen=True)
class StoredArtifact:
    """A committed artifact index row."""

    artifact_ref: ArtifactRef
    agent_turn_id: AgentTurnId
    call_id: CerebroCallId
    tool_key: ToolKey
    binding_generation: ToolBindingGeneration
    content_type: str
    storage_backend: str
    byte_size: int
    content_sha256: str
    retention_policy: str
    provenance: dict[str, Any]
    created_at: str

    def describe(self) -> dict[str, Any]:
        """What logs, Hub events and operator surfaces may see. Never the payload."""
        return {
            "artifact_ref": str(self.artifact_ref),
            "call_id": str(self.call_id),
            "tool_key": self.tool_key.canonical(),
            "binding_generation": str(self.binding_generation),
            "content_type": self.content_type,
            "storage_backend": self.storage_backend,
            "byte_size": self.byte_size,
            "content_sha256": self.content_sha256,
            "retention_policy": self.retention_policy,
        }


class ArtifactWriteFailed(HarnessStateError):
    """Raw output could not be made durable, so no reference may be committed."""


class ArtifactStore:
    """Writes and reads complete raw tool output durably and atomically."""

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            from cerebro.config import settings

            root = Path(settings.data_dir) / _ARTIFACT_DIRNAME
        self.root = Path(root)

    def path_for(self, relative_path: str) -> Path:
        """Resolve a stored relative path, refusing anything that escapes the store."""
        root = self.root.resolve()
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise HarnessStateError(
                f"artifact path {relative_path!r} escapes the Harness artifact store"
            ) from None
        return target

    def stage(
        self,
        raw_output: str,
        *,
        agent_turn_id: AgentTurnId,
        call_id: CerebroCallId,
        tool_key: ToolKey,
        binding_generation: ToolBindingGeneration,
        created_at: str,
        content_type: str = "text/plain; charset=utf-8",
        provenance: dict[str, Any] | None = None,
    ) -> StagedArtifact:
        """Make the exact raw output durable and return an uncommitted reference to it.

        Raises `ArtifactWriteFailed` rather than returning a reference it cannot back, so the
        caller's semantic transaction never opens with a promise it cannot keep.
        """
        encoded = raw_output.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        ref = ArtifactRef(f"artf_{digest[:24]}{str(call_id)[-8:]}")
        record = {
            "agent_turn_id": str(agent_turn_id),
            "call_id": str(call_id),
            "tool_key": tool_key.canonical(),
            "binding_generation": str(binding_generation),
            "created_at": created_at,
            **(provenance or {}),
        }

        if len(encoded) <= INLINE_THRESHOLD_BYTES:
            return StagedArtifact(
                artifact_ref=ref,
                agent_turn_id=agent_turn_id,
                call_id=call_id,
                tool_key=tool_key,
                binding_generation=binding_generation,
                content_type=content_type,
                storage_backend="inline",
                byte_size=len(encoded),
                content_sha256=digest,
                inline_payload=raw_output,
                relative_path=None,
                retention_policy=ARTIFACT_RETENTION_POLICY,
                provenance=record,
                created_at=created_at,
            )

        relative_path = f"{digest[:2]}/{ref}.bin"
        target = self.path_for(relative_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".partial")
            with open(temporary, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            self._sync_directory(target.parent)
        except OSError as exc:
            raise ArtifactWriteFailed(
                f"raw tool output for {call_id} could not be made durable: {exc}"
            ) from exc

        return StagedArtifact(
            artifact_ref=ref,
            agent_turn_id=agent_turn_id,
            call_id=call_id,
            tool_key=tool_key,
            binding_generation=binding_generation,
            content_type=content_type,
            storage_backend="file",
            byte_size=len(encoded),
            content_sha256=digest,
            inline_payload=None,
            relative_path=relative_path,
            retention_policy=ARTIFACT_RETENTION_POLICY,
            provenance=record,
            created_at=created_at,
        )

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        """Best-effort directory fsync so the rename itself survives a power loss.

        Windows has no directory file descriptor to sync, so this is genuinely best effort
        there; the rename is still atomic, which is the property the contract needs.
        """
        try:
            fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    async def read(self, artifact_ref: ArtifactRef) -> str:
        """Read the complete raw output back, verifying it against its recorded digest."""
        from cerebro import db

        row = await db.fetch_one(
            "SELECT * FROM harness_artifacts WHERE artifact_ref = ?", (str(artifact_ref),)
        )
        if row is None:
            raise HarnessRecordNotFound(f"artifact {artifact_ref} does not exist")
        if row["storage_backend"] == "inline":
            payload = row["inline_payload"] or ""
        else:
            payload = self.path_for(row["relative_path"]).read_text(encoding="utf-8")
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if digest != row["content_sha256"]:
            raise HarnessStateError(
                f"artifact {artifact_ref} does not match its recorded SHA-256; the durable raw "
                f"evidence has been altered"
            )
        return payload
