"""Internal kiosk vocabulary, not an agreed backend/network schema.

The controller executes effects and supplies facts. It owns reader validation,
same-card assurance, readiness checks, and timer durations; handle() performs no I/O.
"""

from dataclasses import dataclass
from enum import StrEnum


class KioskState(StrEnum):
    IDLE = "idle"
    ACTIVATING = "activating"
    AWAITING_IDENTITY = "awaiting_identity"
    REGISTERING = "registering"
    RESULT = "result"
    OFFLINE = "offline"
    READER_ERROR = "reader_error"
    OUTCOME_UNKNOWN = "outcome_unknown"


class BackendOp(StrEnum):
    ACTIVATE_UID = "activate_uid"
    REGISTER_AND_ACTIVATE = "register_and_activate"


class Outcome(StrEnum):
    ACTIVATED = "activated"
    ALREADY_ACTIVE = "already_active"
    UNREGISTERED = "unregistered"  # Routing only; this is not an unknown student.
    REGISTERED_AND_ACTIVE = "registered_and_active"
    REPLACED_AND_ACTIVE = "replaced_and_active"
    UNKNOWN_STUDENT = "unknown_student"  # Display 1: account-signup QR.
    MISSING_INDUCTION = "missing_induction"  # Display 1: training-signup QR.
    DENIED = "denied"
    UID_CONFLICT = "uid_conflict"
    READ_AGAIN = "read_again"  # Local feedback, never a backend response.
    SESSION_EXPIRED = "session_expired"  # Local feedback, never a backend response.


class FailureKind(StrEnum):
    NOT_SENT = "not_sent"  # Only when the controller knows no request was sent.
    UNKNOWN = "unknown"  # Includes lost responses and possible partial writes.


class TimeoutName(StrEnum):
    SESSION = "session"
    RESULT = "result"


@dataclass(frozen=True)
class UidScan:
    """A fresh presentation after the required RF commands were acknowledged.

    Allocate increasing session IDs only when IDLE and ready; never reuse an ID.
    Further reads from that presentation retain its ID, including conflicting reads.
    """

    session_id: int
    uid: str


@dataclass(frozen=True)
class IdentityConfirmed:
    """The controller has established that BOTH identifiers belong to one card.

    A shared session ID or a short time window is not sufficient evidence. Real
    hardware must not emit this until the same-card mechanism has been validated.
    """

    session_id: int
    uid: str
    student_number: str


@dataclass(frozen=True)
class BadScan:
    """The current presentation is ambiguous/corrupt, not merely missing optional input."""

    session_id: int
    reason: str


@dataclass(frozen=True)
class CancelSession:
    session_id: int


@dataclass(frozen=True)
class BackendResult:
    """An authoritative result for the original (session_id, op) operation.

    Success includes current eligibility and activation. Replacement success also
    includes invalidation of the old UID. Denials and UNREGISTERED imply no write.
    reason is a backend reason code; the approved display mapping is still open.
    """

    session_id: int
    op: BackendOp
    outcome: Outcome
    reason: str | None = None


@dataclass(frozen=True)
class BackendError:
    session_id: int
    op: BackendOp
    kind: FailureKind = FailureKind.UNKNOWN


@dataclass(frozen=True)
class BackendOnline:
    pass


@dataclass(frozen=True)
class BackendOffline:
    pass


@dataclass(frozen=True)
class ReaderReady:
    """Current reader readiness has been verified, including after any recovery."""

    session_id: int


@dataclass(frozen=True)
class ReaderFault:
    session_id: int
    reason: str


@dataclass(frozen=True)
class Timeout:
    session_id: int
    name: TimeoutName


Event = (
    UidScan
    | IdentityConfirmed
    | BadScan
    | CancelSession
    | BackendResult
    | BackendError
    | BackendOnline
    | BackendOffline
    | ReaderReady
    | ReaderFault
    | Timeout
)


@dataclass(frozen=True)
class ActivateUid:
    session_id: int
    uid: str


@dataclass(frozen=True)
class RegisterAndActivate:
    """One logical operation; the backend decides new registration versus replacement."""

    session_id: int
    uid: str
    student_number: str


@dataclass(frozen=True)
class CaptureIdentity:
    """Schedule optional identity capture concurrently with UID activation, without blocking."""

    session_id: int
    uid: str


@dataclass(frozen=True)
class StopCapture:
    """Discard this presentation's buffered input and rearm the readers safely.

    Report any failure as ReaderFault. This does not cancel or undo a backend write.
    """

    session_id: int


@dataclass(frozen=True)
class StartTimeout:
    session_id: int
    name: TimeoutName


@dataclass(frozen=True)
class CancelTimeout:
    session_id: int
    name: TimeoutName


Effect = (
    ActivateUid | RegisterAndActivate | CaptureIdentity | StopCapture | StartTimeout | CancelTimeout
)
