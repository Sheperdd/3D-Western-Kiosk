from dataclasses import dataclass, replace

from kiosk.events import (
    AdjustStock,
    Alert,
    AlertSeverity,
    CancelTimeout,
    CreateLink,
    Effect,
    Event,
    GetTraining,
    KioskState,
    LinkResult,
    LinkStatus,
    MotorDevice,
    MotorDirection,
    MotorDone,
    MoveMotor,
    StartTimeout,
    StockChanged,
    StudentScan,
    TimeoutName,
    TrainingResult,
    TrainingStatus,
    UidScan,
)


@dataclass(frozen=True)
class Context:
    student_number: str | None = None
    close_retry_count: int = 0
    stock: int = 0


MAX_CLOSE_RETRIES = 3


def _end_session(ctx: Context) -> Context:
    return replace(ctx, student_number=None, close_retry_count=0)


def handle(
    state: KioskState, ctx: Context, event: Event
) -> tuple[KioskState, Context, list[Effect]]:

    if isinstance(event, StockChanged):
        return (
            (KioskState.IDLE if state == KioskState.OUT_OF_STOCK and event.stock > 0 else state),
            replace(ctx, stock=event.stock),
            [],
        )

    match state, event:
        case KioskState.IDLE, StudentScan(student_number):
            return (
                KioskState.CHECKING_TRAINING,
                replace(ctx, student_number=student_number),
                [GetTraining(student_number)],
            )
        case KioskState.CHECKING_TRAINING, TrainingResult(TrainingStatus.TRAINED):
            if ctx.stock <= 0:
                return (
                    KioskState.OUT_OF_STOCK,
                    _end_session(ctx),
                    [Alert(AlertSeverity.ROUTINE, "Out of stock")],
                )
            return (
                KioskState.DISPENSE_OPENING,
                ctx,
                [MoveMotor(device=MotorDevice.IRIS, direction=MotorDirection.OPEN)],
            )
        case KioskState.DISPENSE_OPENING, MotorDone(MotorDevice.IRIS, MotorDirection.OPEN):
            return (
                KioskState.DISPENSE_OPEN,
                ctx,
                [StartTimeout(name=TimeoutName.DISPENSE_OPEN)],
            )
        case KioskState.DISPENSE_OPEN, UidScan(uid):
            assert ctx.student_number is not None, "Student number should be set in context"
            return (
                KioskState.LINKING,
                ctx,
                [
                    CreateLink(student_number=ctx.student_number, uid=uid),
                    CancelTimeout(name=TimeoutName.DISPENSE_OPEN),
                ],
            )
        case KioskState.LINKING, LinkResult(LinkStatus.SUCCESS):
            return (
                KioskState.DISPENSE_CLOSING,
                ctx,
                [
                    MoveMotor(device=MotorDevice.IRIS, direction=MotorDirection.CLOSE),
                    AdjustStock(-1),
                ],
            )
        case KioskState.DISPENSE_CLOSING, MotorDone(MotorDevice.IRIS, MotorDirection.CLOSE):
            return KioskState.IDLE, _end_session(ctx), []
        case _:
            return state, ctx, []
