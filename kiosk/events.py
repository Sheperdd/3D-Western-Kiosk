"""Internal kiosk vocabulary. Gatekeeper results reuse the wire strings from docs/kiosk-api.md.

The controller executes effects and supplies facts. It owns reader validation,
readiness checks, the gatekeeper HTTP call, and timer durations; handle() performs no I/O.
"""

from dataclasses import dataclass
from enum import StrEnum


class KioskState(StrEnum):
    IDLE = "idle"
    CHECKING = "checking"
    RESULT = "result"
    OFFLINE = "offline"
    READER_ERROR = "reader_error"


class Result(StrEnum):
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    DENIED = "DENIED"
    IGNORED_DUPLICATE = "IGNORED_DUPLICATE"  # Repeats the previous answer; render it again.
    READ_AGAIN = "READ_AGAIN"  # Local feedback, never a gatekeeper response.
    UNREACHABLE = "UNREACHABLE"  # Local feedback, never a gatekeeper response.
    NOT_SET_UP = "NOT_SET_UP"  # Local feedback, never a gatekeeper response.


class FailureKind(StrEnum):
    UNREACHABLE = "unreachable"  # Timeout or network error, after the one contract retry.
    BAD_REQUEST = "bad_request"  # 422: malformed body, usually a bad card read.
    BAD_KEY = "bad_key"  # 401: missing, wrong or rotated device key.


class TimeoutName(StrEnum):
    TAP = "tap"
    RESULT = "result"


@dataclass(frozen=True)
class CardRead:
    """Both observed identifiers, after UID capture and acknowledged RF handover.

    Allocate increasing tap IDs only when IDLE and ready; never reuse an ID.
    This is NOT proof that the identifiers belong to the same physical card.
    """

    tap_id: int
    uid: str
    student_number: str


@dataclass(frozen=True)
class BadScan:
    """The current attempt is incomplete or ambiguous; no new tap ID is allocated."""

    tap_id: int
    reason: str


@dataclass(frozen=True)
class CancelSession:
    tap_id: int


@dataclass(frozen=True)
class GatekeeperResult:
    """The gatekeeper's answer to a tap. reason stays a raw code: unknown codes must not crash."""

    tap_id: int
    result: Result
    reason: str | None = None
    message: str | None = None
    notices: tuple[str, ...] = ()
    first_name: str | None = None


@dataclass(frozen=True)
class GatekeeperError:
    tap_id: int
    kind: FailureKind = FailureKind.UNREACHABLE


@dataclass(frozen=True)
class GatekeeperOnline:
    pass


@dataclass(frozen=True)
class GatekeeperOffline:
    pass


@dataclass(frozen=True)
class ReaderReady:
    """Current reader readiness has been verified, including after any recovery."""

    tap_id: int


@dataclass(frozen=True)
class ReaderFault:
    tap_id: int
    reason: str


@dataclass(frozen=True)
class Timeout:
    tap_id: int
    name: TimeoutName


Event = (
    CardRead
    | BadScan
    | CancelSession
    | GatekeeperResult
    | GatekeeperError
    | GatekeeperOnline
    | GatekeeperOffline
    | ReaderReady
    | ReaderFault
    | Timeout
)


@dataclass(frozen=True)
class Tap:
    """POST /v1/kiosk/tap: the gatekeeper checks in or out by student number."""

    tap_id: int
    uid: str
    student_number: str


@dataclass(frozen=True)
class StartTimeout:
    tap_id: int
    name: TimeoutName


@dataclass(frozen=True)
class CancelTimeout:
    tap_id: int
    name: TimeoutName


Effect = Tap | StartTimeout | CancelTimeout
