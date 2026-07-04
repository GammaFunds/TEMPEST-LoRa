from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from .display_contract import (
    DISPLAY_SESSION_SCHEMA,
    R2E1_CONTRACT_SHA256,
    ExactKmsSnapshot,
    PreparedScanoutBuffers,
    ValidatedDynamicDisplayArtifact,
    prepare_scanout_buffers,
)
from .pixel_renderer import DynamicRenderedPixelArtifact
from .protocol import ProtocolError, canonical_json_bytes


class DisplayState(str, Enum):
    CLOSED = "CLOSED"
    ARTIFACT_VALIDATED = "ARTIFACT_VALIDATED"
    SNAPSHOT_VALIDATED = "SNAPSHOT_VALIDATED"
    BUFFERS_READY = "BUFFERS_READY"
    TEST_ONLY_PASSED = "TEST_ONLY_PASSED"
    GUARD_BLACK_ARMED = "GUARD_BLACK_ARMED"
    RUNNING = "RUNNING"
    FINAL_BLACK_PENDING = "FINAL_BLACK_PENDING"
    COMPLETE = "COMPLETE"
    ABORT_BLACK_PENDING = "ABORT_BLACK_PENDING"
    FAILED = "FAILED"


class ScheduleKind(str, Enum):
    GUARD_BEFORE = "guard-before"
    DATA = "data"
    GUARD_AFTER = "guard-after"
    ABORT_GUARD = "abort-guard"


@dataclass(frozen=True)
class ScheduledFrame:
    kind: ScheduleKind
    data_index: int | None
    framebuffer_token: str
    framebuffer_sha256: str
    hold_vblanks: int = 1

    def descriptor(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "data_index": self.data_index,
            "framebuffer_token": self.framebuffer_token,
            "framebuffer_sha256": self.framebuffer_sha256,
            "hold_vblanks": self.hold_vblanks,
        }


@dataclass(frozen=True)
class FlipEvent:
    crtc_id: int
    sequence: int
    monotonic_ns: int

    def descriptor(self) -> dict[str, int]:
        return {
            "crtc_id": self.crtc_id,
            "sequence": self.sequence,
            "monotonic_ns": self.monotonic_ns,
        }


@dataclass(frozen=True)
class FakeFailurePlan:
    test_only_fail_at: int | None = None
    commit_fail_at: int | None = None
    event_timeout_at: int | None = None
    wrong_crtc_at: int | None = None
    duplicate_sequence_at: int | None = None
    sequence_gap_at: int | None = None
    reverse_sequence_at: int | None = None
    out_fence_error_at: int | None = None
    duplicate_timestamp_at: int | None = None
    reverse_timestamp_at: int | None = None
    topology_change_after_preflight: bool = False
    runtime_topology_change_at: int | None = None

    def validate(self) -> None:
        if type(self) is not FakeFailurePlan:
            raise ProtocolError("failure plan must be exact FakeFailurePlan")
        for name in (
            "test_only_fail_at", "commit_fail_at", "event_timeout_at",
            "wrong_crtc_at", "duplicate_sequence_at", "sequence_gap_at",
            "reverse_sequence_at", "out_fence_error_at", "duplicate_timestamp_at",
            "reverse_timestamp_at", "runtime_topology_change_at",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ProtocolError(f"{name} must be None or a nonnegative plain integer")
        if type(self.topology_change_after_preflight) is not bool:
            raise ProtocolError("topology_change_after_preflight must be exact boolean")


@dataclass(frozen=True)
class DisplaySessionResult:
    success: bool
    final_state: DisplayState
    state_history: tuple[DisplayState, ...]
    events: tuple[FlipEvent, ...]
    error: str | None
    abort_black_attempted: bool
    test_only_calls: int
    commit_calls: int
    manifest_json: bytes


class FakeAtomicKmsAdapter:
    """Offline-only fake. It has no OS, DRM, file, subprocess, or network access."""

    def __init__(
        self,
        *,
        snapshot: ExactKmsSnapshot,
        starting_sequence: int = 1000,
        starting_monotonic_ns: int = 1_000_000_000,
        failure_plan: FakeFailurePlan | None = None,
    ) -> None:
        if type(snapshot) is not ExactKmsSnapshot:
            raise ProtocolError("snapshot must be exact ExactKmsSnapshot")
        snapshot.validate()
        if type(starting_sequence) is not int or starting_sequence < 0:
            raise ProtocolError("starting_sequence must be nonnegative plain integer")
        if type(starting_monotonic_ns) is not int or starting_monotonic_ns < 0:
            raise ProtocolError("starting_monotonic_ns must be nonnegative plain integer")
        if failure_plan is None:
            failure_plan = FakeFailurePlan()
        failure_plan.validate()
        self._snapshot = snapshot
        self._starting_sequence = starting_sequence
        self._starting_monotonic_ns = starting_monotonic_ns
        self._failure_plan = failure_plan
        self._snapshot_calls = 0
        self._test_only_calls: list[tuple[str, bool]] = []
        self._commit_calls: list[str] = []
        self._pending: tuple[str, int] | None = None
        self._event_index = 0
        self._last_sequence = starting_sequence

    @property
    def test_only_calls(self) -> tuple[tuple[str, bool], ...]:
        return tuple(self._test_only_calls)

    @property
    def commit_calls(self) -> tuple[str, ...]:
        return tuple(self._commit_calls)

    def snapshot(self) -> ExactKmsSnapshot:
        self._snapshot_calls += 1
        if self._failure_plan.topology_change_after_preflight and self._snapshot_calls >= 2:
            return replace(self._snapshot, topology_token=self._snapshot.topology_token + "-changed")
        runtime_at = self._failure_plan.runtime_topology_change_at
        if runtime_at is not None and len(self._commit_calls) > runtime_at:
            return replace(self._snapshot, topology_token=self._snapshot.topology_token + "-runtime-changed")
        return self._snapshot

    def test_only(self, frame: ScheduledFrame, *, allow_modeset: bool) -> None:
        index = len(self._test_only_calls)
        self._test_only_calls.append((frame.framebuffer_token, allow_modeset))
        if self._failure_plan.test_only_fail_at == index:
            raise ProtocolError("fake TEST_ONLY failure")
        if index == 0 and allow_modeset is not True:
            raise ProtocolError("initial guard TEST_ONLY must allow modeset")
        if index > 0 and allow_modeset is not False:
            raise ProtocolError("FB-only TEST_ONLY must not allow modeset")

    def submit(self, frame: ScheduledFrame) -> None:
        index = len(self._commit_calls)
        if self._pending is not None:
            raise ProtocolError("fake EBUSY: one commit is already outstanding")
        self._commit_calls.append(frame.framebuffer_token)
        if self._failure_plan.commit_fail_at == index:
            raise ProtocolError("fake atomic commit failure")
        self._pending = (frame.framebuffer_token, index)

    def wait_flip_event(self) -> FlipEvent:
        if self._pending is None:
            raise ProtocolError("no fake commit is pending")
        _, commit_index = self._pending
        if self._failure_plan.event_timeout_at == commit_index:
            self._pending = None
            raise ProtocolError("fake flip event timeout")
        if self._failure_plan.out_fence_error_at == commit_index:
            self._pending = None
            raise ProtocolError("fake out-fence error")

        sequence = self._last_sequence + 1
        if self._failure_plan.wrong_crtc_at == commit_index:
            crtc_id = self._snapshot.crtc_id + 1
        else:
            crtc_id = self._snapshot.crtc_id
        if self._failure_plan.duplicate_sequence_at == commit_index:
            sequence = self._last_sequence
        elif self._failure_plan.sequence_gap_at == commit_index:
            sequence = self._last_sequence + 2
        elif self._failure_plan.reverse_sequence_at == commit_index:
            sequence = max(0, self._last_sequence - 1)

        monotonic_ns = self._starting_monotonic_ns + self._event_index * 16_666_667
        if self._failure_plan.duplicate_timestamp_at == commit_index and self._event_index > 0:
            monotonic_ns -= 16_666_667
        elif self._failure_plan.reverse_timestamp_at == commit_index and self._event_index > 0:
            monotonic_ns -= 16_666_668

        event = FlipEvent(
            crtc_id=crtc_id,
            sequence=sequence,
            monotonic_ns=monotonic_ns,
        )
        self._pending = None
        self._event_index += 1
        self._last_sequence = sequence
        return event


def build_frame_schedule(buffers: PreparedScanoutBuffers) -> tuple[ScheduledFrame, ...]:
    if type(buffers) is not PreparedScanoutBuffers:
        raise ProtocolError("buffers must be exact PreparedScanoutBuffers")
    guard_token = f"guard:{buffers.guard_black_sha256}"
    schedule: list[ScheduledFrame] = [
        ScheduledFrame(
            kind=ScheduleKind.GUARD_BEFORE,
            data_index=None,
            framebuffer_token=guard_token,
            framebuffer_sha256=buffers.guard_black_sha256,
        )
    ]
    for index, frame_hash in enumerate(buffers.data_xrgb8888_sha256):
        schedule.append(
            ScheduledFrame(
                kind=ScheduleKind.DATA,
                data_index=index,
                framebuffer_token=f"data:{index}:{frame_hash}",
                framebuffer_sha256=frame_hash,
            )
        )
    schedule.append(
        ScheduledFrame(
            kind=ScheduleKind.GUARD_AFTER,
            data_index=None,
            framebuffer_token=guard_token,
            framebuffer_sha256=buffers.guard_black_sha256,
        )
    )
    return tuple(schedule)


def _manifest(
    *,
    success: bool,
    state_history: list[DisplayState],
    events: list[FlipEvent],
    error: str | None,
    abort_black_attempted: bool,
    snapshot_descriptor: dict[str, Any],
    validated: ValidatedDynamicDisplayArtifact,
    schedule: tuple[ScheduledFrame, ...],
    adapter: FakeAtomicKmsAdapter,
) -> bytes:
    value = {
        "schema": DISPLAY_SESSION_SCHEMA,
        "execution_mode": "offline-fake-atomic-kms",
        "success": success,
        "final_state": state_history[-1].value,
        "state_history": [state.value for state in state_history],
        "error": error,
        "abort_black_attempted": abort_black_attempted,
        "design_contract": {
            "r2e1_contract_sha256": R2E1_CONTRACT_SHA256,
            "repository_basis_commit": "8e326e2e4537e5afb2f3823f79bf1671e2a180aa",
            "repository_basis_tree": "d8c247dab46da5f8bc753649d8d5c31aa4bd1925",
            "identity_scope": "R2E.1 design basis; not a claim about the current checkout",
        },
        "artifact": {
            "manifest_sha256": validated.manifest_sha256,
            "renderer_descriptor_sha256": validated.renderer_descriptor_sha256,
            "envelope_sha256": validated.envelope_sha256,
            "timeline_sha256": validated.timeline_sha256,
            "frame_count": validated.frame_count,
            "raw_frame_sha256": list(validated.raw_frame_sha256),
            "pgm_frame_sha256": list(validated.pgm_frame_sha256),
        },
        "kms_snapshot": snapshot_descriptor,
        "schedule": [frame.descriptor() for frame in schedule],
        "events": [event.descriptor() for event in events],
        "test_only_calls": [
            {"framebuffer_token": token, "allow_modeset": allow_modeset}
            for token, allow_modeset in adapter.test_only_calls
        ],
        "commit_calls": list(adapter.commit_calls),
        "nonclaims": [
            "no live DRM/KMS access",
            "no physical pixel-clock accuracy proof",
            "no RF emission or LoRa decodability proof",
            "no protected MATLAB/P-code equivalence claim",
        ],
    }
    return canonical_json_bytes(value)


def run_offline_display_session(
    *,
    artifact: DynamicRenderedPixelArtifact,
    snapshot: ExactKmsSnapshot,
    adapter: FakeAtomicKmsAdapter,
) -> DisplaySessionResult:
    if type(adapter) is not FakeAtomicKmsAdapter:
        raise ProtocolError("R2E.2 accepts only exact FakeAtomicKmsAdapter")
    if type(snapshot) is not ExactKmsSnapshot:
        raise ProtocolError("snapshot must be exact ExactKmsSnapshot")

    state_history = [DisplayState.CLOSED]
    events: list[FlipEvent] = []
    error: str | None = None
    abort_attempted = False
    schedule: tuple[ScheduledFrame, ...] = ()
    buffers: PreparedScanoutBuffers | None = None
    live_started = False
    topology_stable = True
    snapshot_descriptor: dict[str, Any] = {
        "schema": "tempest-lora.rejected-kms-snapshot.v1",
        "validation_status": "not-yet-validated",
    }

    try:
        buffers = prepare_scanout_buffers(artifact)
        state_history.append(DisplayState.ARTIFACT_VALIDATED)

        snapshot.validate()
        snapshot_descriptor = snapshot.descriptor()
        initial_snapshot = adapter.snapshot()
        if initial_snapshot != snapshot:
            raise ProtocolError("adapter snapshot differs from caller-approved snapshot")
        state_history.append(DisplayState.SNAPSHOT_VALIDATED)

        schedule = build_frame_schedule(buffers)
        state_history.append(DisplayState.BUFFERS_READY)

        for index, frame in enumerate(schedule):
            adapter.test_only(frame, allow_modeset=(index == 0))
        if adapter.snapshot() != initial_snapshot:
            topology_stable = False
            raise ProtocolError("KMS topology changed between snapshot and arming")
        state_history.append(DisplayState.TEST_ONLY_PASSED)

        previous_sequence: int | None = None
        previous_monotonic_ns: int | None = None
        for index, frame in enumerate(schedule):
            if index == 0:
                state_history.append(DisplayState.GUARD_BLACK_ARMED)
            elif frame.kind is ScheduleKind.DATA and state_history[-1] is not DisplayState.RUNNING:
                state_history.append(DisplayState.RUNNING)
            elif frame.kind is ScheduleKind.GUARD_AFTER:
                state_history.append(DisplayState.FINAL_BLACK_PENDING)

            adapter.submit(frame)
            live_started = True
            event = adapter.wait_flip_event()
            if event.crtc_id != snapshot.crtc_id:
                raise ProtocolError("flip event CRTC mismatch")
            if previous_sequence is not None and event.sequence != previous_sequence + 1:
                raise ProtocolError("flip event sequence is not consecutive")
            if type(event.monotonic_ns) is not int or event.monotonic_ns < 0:
                raise ProtocolError("flip event monotonic timestamp mismatch")
            if previous_monotonic_ns is not None and event.monotonic_ns <= previous_monotonic_ns:
                raise ProtocolError("flip event monotonic timestamp is not strictly increasing")
            previous_sequence = event.sequence
            previous_monotonic_ns = event.monotonic_ns
            events.append(event)
            if adapter.snapshot() != initial_snapshot:
                topology_stable = False
                raise ProtocolError("KMS topology changed during running schedule")

        state_history.append(DisplayState.COMPLETE)
        manifest = _manifest(
            success=True,
            state_history=state_history,
            events=events,
            error=None,
            abort_black_attempted=False,
            snapshot_descriptor=snapshot_descriptor,
            validated=buffers.validated,
            schedule=schedule,
            adapter=adapter,
        )
        return DisplaySessionResult(
            success=True,
            final_state=DisplayState.COMPLETE,
            state_history=tuple(state_history),
            events=tuple(events),
            error=None,
            abort_black_attempted=False,
            test_only_calls=len(adapter.test_only_calls),
            commit_calls=len(adapter.commit_calls),
            manifest_json=manifest,
        )
    except ProtocolError as exc:
        error = str(exc)
        if snapshot_descriptor.get("validation_status") == "not-yet-validated":
            snapshot_descriptor = {
                "schema": "tempest-lora.rejected-kms-snapshot.v1",
                "validation_status": "rejected",
                "validation_error": error,
            }
        if live_started and buffers is not None and topology_stable:
            abort_attempted = True
            state_history.append(DisplayState.ABORT_BLACK_PENDING)
            abort = ScheduledFrame(
                kind=ScheduleKind.ABORT_GUARD,
                data_index=None,
                framebuffer_token=f"abort-guard:{buffers.guard_black_sha256}",
                framebuffer_sha256=buffers.guard_black_sha256,
            )
            try:
                adapter.submit(abort)
                abort_event = adapter.wait_flip_event()
                if abort_event.crtc_id == snapshot.crtc_id:
                    events.append(abort_event)
            except ProtocolError:
                pass
        state_history.append(DisplayState.FAILED)

        if buffers is None:
            # Preserve a deterministic minimal artifact identity for pre-validation failures.
            validated = ValidatedDynamicDisplayArtifact(
                manifest_sha256=hashlib.sha256(artifact.manifest_json if type(artifact) is DynamicRenderedPixelArtifact else b"").hexdigest(),
                renderer_descriptor_sha256="0" * 64,
                envelope_sha256="0" * 64,
                timeline_sha256=hashlib.sha256(artifact.timeline_u8 if type(artifact) is DynamicRenderedPixelArtifact and type(artifact.timeline_u8) is bytes else b"").hexdigest(),
                frame_count=len(artifact.visible_frames_u8) if type(artifact) is DynamicRenderedPixelArtifact and type(artifact.visible_frames_u8) is tuple else 0,
                raw_frame_sha256=(),
                pgm_frame_sha256=(),
            )
        else:
            validated = buffers.validated
        manifest = _manifest(
            success=False,
            state_history=state_history,
            events=events,
            error=error,
            abort_black_attempted=abort_attempted,
            snapshot_descriptor=snapshot_descriptor,
            validated=validated,
            schedule=schedule,
            adapter=adapter,
        )
        return DisplaySessionResult(
            success=False,
            final_state=DisplayState.FAILED,
            state_history=tuple(state_history),
            events=tuple(events),
            error=error,
            abort_black_attempted=abort_attempted,
            test_only_calls=len(adapter.test_only_calls),
            commit_calls=len(adapter.commit_calls),
            manifest_json=manifest,
        )
