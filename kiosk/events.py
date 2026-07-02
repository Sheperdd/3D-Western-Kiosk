# This file defines the three vocabularies of the whole kiosk system:
# 1. Events - facts that have already happened, flowing into the machine. "UID was scanned", etc.
# 2. States - the finite set of states that the kiosk can be in. IDLE, CHECKING_TRAINING, etc.
# 3. Effects - instructions the machine hands back for the controller to execute.
# "Open the iris door", "Call create_link with this UID", etc.

from dataclasses import dataclass
from enum import StrEnum

# EVENTS


@dataclass(frozen=True)
class StudentScan:
    student_number: str


@dataclass(frozen=True)
class UidScan:
    uid: str


# Every BadScan event lands in the same ERROR_TRANSIENT state,
# but the reason is useful for logging and debugging.
@dataclass(frozen=True)
class BadScan:
    reason: str


class TrainingStatus(StrEnum):  # TODO: talk with backend team
    TRAINED = "trained"  # the student is trained, proceed
    NOT_TRAINED = "not_trained"  # the student is not trained, tell them website to get trained
    HAS_CARD_OUT = "has_card_out"  # the student alr has a makerspace card out
    UNKNOWN_STUDENT = (
        "unknown_student"  # the student is not in the database, show QR code to sign up
    )


@dataclass(frozen=True)
class TrainingResult:
    status: TrainingStatus


class LinkStatus(StrEnum):
    SUCCESS = "success"
    UID_NOT_IN_DATABASE = "uid_not_in_database"
    CARD_ALREADY_LINKED = "card_already_linked"
    STUDENT_ALREADY_HAS_CARD = "student_already_has_card"


@dataclass(frozen=True)
class LinkResult:
    status: LinkStatus


class BackendErrorOp(StrEnum):
    GET_TRAINING = "get_training"
    CHECK_CARD = "check_card"
    CREATE_LINK = "create_link"
    DELETE_LINK = "delete_link"


@dataclass(frozen=True)
class BackendError:
    op: BackendErrorOp


@dataclass(frozen=True)
class BackendOnline:
    pass


@dataclass(frozen=True)
class BackendOffline:
    pass


class MotorDevice(StrEnum):
    IRIS = "iris"
    DRAWER = "drawer"


class MotorDirection(StrEnum):
    OPEN = "open"
    CLOSE = "close"


@dataclass(frozen=True)
class MotorDone:
    device: MotorDevice
    direction: MotorDirection


@dataclass(frozen=True)
class MotorJam:
    device: MotorDevice
    direction: MotorDirection


class TimeoutName(StrEnum):
    DISPENSE_OPEN = "dispense_open"
    DRAWER_DWELL = "drawer_dwell"
    TRANSIENT_ERROR = "transient_error"
    QR_CODE = "qr_code"


@dataclass(frozen=True)
class Timeout:
    name: TimeoutName


@dataclass(frozen=True)
class StockChanged:
    stock: int


class AdminOp(StrEnum):
    CLEAR_OUT_OF_SERVICE = "clear_out_of_service"
    CANCEL_SESSION = "cancel_session"


@dataclass(frozen=True)
class AdminCommand:
    command: AdminOp


Event = (
    StudentScan
    | UidScan
    | BadScan
    | TrainingResult
    | LinkResult
    | BackendError
    | BackendOnline
    | BackendOffline
    | MotorDone
    | MotorJam
    | Timeout
    | StockChanged
    | AdminCommand
)

# STATES


class KioskState(StrEnum):
    BOOTING = "booting"
    IDLE = "idle"
    CHECKING_TRAINING = "checking_training"
    NOT_TRAINED = "not_trained"
    ALREADY_HAS_CARD = "already_has_card"
    UNKNOWN_STUDENT = "unknown_student"
    DISPENSE_OPENING = "dispense_opening"
    DISPENSE_OPEN = "dispense_open"
    LINKING = "linking"
    DISPENSE_CLOSING = "dispense_closing"
    RETURN_OPENING = "return_opening"
    RETURN_OPEN = "return_open"
    RETURN_CLOSING = "return_closing"
    OUT_OF_STOCK = "out_of_stock"
    OFFLINE = "offline"  # wifi down or backend unreachable
    ERROR_TRANSIENT = (
        "error_transient"  # bad read | unknown UID card | wrong card type | backend error
    )
    OUT_OF_SERVICE = "out_of_service"  # iris fail | unrecoverable motor jam


# EFFECTS
# Motor commands
@dataclass(frozen=True)
class MoveMotor:
    device: MotorDevice
    direction: MotorDirection


# Backend commands
@dataclass(frozen=True)
class GetTraining:
    student_number: str


@dataclass(frozen=True)
class CheckCard:
    uid: str


@dataclass(frozen=True)
class CreateLink:
    student_number: str
    uid: str


@dataclass(frozen=True)
class DeleteLink:
    uid: str


@dataclass(frozen=True)
class StartTimeout:
    name: TimeoutName


@dataclass(frozen=True)
class CancelTimeout:
    name: TimeoutName


@dataclass(frozen=True)
class EnqueueUnlink:
    uid: str


class AlertSeverity(StrEnum):
    URGENT = "urgent"
    ROUTINE = "routine"


@dataclass(frozen=True)
class Alert:
    severity: AlertSeverity
    message: str


@dataclass(frozen=True)
class AdjustStock:
    delta: int


Effect = (
    MoveMotor
    | GetTraining
    | CheckCard
    | CreateLink
    | DeleteLink
    | StartTimeout
    | CancelTimeout
    | EnqueueUnlink
    | Alert
    | AdjustStock
)
