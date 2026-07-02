from kiosk.events import (
    AdjustStock,
    Alert,
    AlertSeverity,
    CancelTimeout,
    CreateLink,
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
from kiosk.machine import Context, handle


# IDLE, Scan student card -> CHECKING_TRAINING, GetTraining(student_number)
def test_idle_student_scan_starts_training_check() -> None:
    state, ctx, effects = handle(
        KioskState.IDLE, Context(stock=5), StudentScan(student_number="12345678")
    )

    assert state == KioskState.CHECKING_TRAINING
    assert ctx == Context(student_number="12345678", stock=5)
    assert effects == [GetTraining("12345678")]


# CHECKING_TRAINING, TrainingResult(TRAINED) -> DISPENSE_OPENING, MoveMotor(IRIS, OPEN)
def test_is_trained_has_stock_dispense_opens() -> None:
    state, ctx, effects = handle(
        KioskState.CHECKING_TRAINING,
        Context(student_number="12345678", stock=1),
        TrainingResult(TrainingStatus.TRAINED),
    )

    assert state == KioskState.DISPENSE_OPENING
    assert ctx == Context(student_number="12345678", stock=1)
    assert effects == [MoveMotor(device=MotorDevice.IRIS, direction=MotorDirection.OPEN)]


# Student is trained but there is no stock, should go to OUT_OF_STOCK and alert
def test_is_trained_no_stock_goes_to_out_of_stock() -> None:
    state, ctx, effects = handle(
        KioskState.CHECKING_TRAINING,
        Context(student_number="12345678", stock=0),
        TrainingResult(TrainingStatus.TRAINED),
    )

    assert state == KioskState.OUT_OF_STOCK
    assert ctx == Context(stock=0)
    assert effects == [Alert(AlertSeverity.ROUTINE, "Out of stock")]


# DISPENSE_OPENING, MotorDone(IRIS, OPEN) -> DISPENSE_OPEN, StartTimeout(DISPENSE_OPEN)
def test_dispense_opening_motor_done_goes_to_dispense_open() -> None:
    state, ctx, effects = handle(
        KioskState.DISPENSE_OPENING,
        Context(student_number="12345678", stock=1),
        MotorDone(device=MotorDevice.IRIS, direction=MotorDirection.OPEN),
    )

    assert state == KioskState.DISPENSE_OPEN
    assert ctx == Context(student_number="12345678", stock=1)
    assert effects == [StartTimeout(name=TimeoutName.DISPENSE_OPEN)]


# DISPENSE_OPEN, UidScan(uid) -> LINKING, CreateLink(student_number, uid),
# CancelTimeout(DISPENSE_OPEN)
def test_dispense_open_student_scan_card_now_linking() -> None:
    state, ctx, effects = handle(
        KioskState.DISPENSE_OPEN,
        Context(student_number="12345678", stock=1),
        UidScan(uid="ABCDEFGH"),
    )

    assert state == KioskState.LINKING
    assert ctx == Context(student_number="12345678", stock=1)
    assert effects == [
        CreateLink(student_number="12345678", uid="ABCDEFGH"),
        CancelTimeout(name=TimeoutName.DISPENSE_OPEN),
    ]


# LINKING, LinkResult(SUCCESS) -> DISPENSE_CLOSING, MoveMotor(IRIS, CLOSE), AdjustStock(-1)
def test_link_success_goes_to_dispense_closing() -> None:
    state, ctx, effects = handle(
        KioskState.LINKING,
        Context(student_number="12345678", stock=1),
        LinkResult(LinkStatus.SUCCESS),
    )

    assert state == KioskState.DISPENSE_CLOSING
    assert ctx == Context(student_number="12345678", stock=1)
    assert effects == [
        MoveMotor(device=MotorDevice.IRIS, direction=MotorDirection.CLOSE),
        AdjustStock(-1),
    ]


# DISPENSE_CLOSING, MotorDone(IRIS, CLOSE) -> IDLE
def test_dispense_closing_motor_done_goes_to_idle() -> None:
    state, ctx, effects = handle(
        KioskState.DISPENSE_CLOSING,
        Context(student_number="12345678", stock=1),
        MotorDone(device=MotorDevice.IRIS, direction=MotorDirection.CLOSE),
    )

    assert state == KioskState.IDLE
    assert ctx == Context(student_number=None, close_retry_count=0, stock=1)
    assert effects == []


# StockChanged
def test_stock_changed_updates_context() -> None:
    state, ctx, effects = handle(
        KioskState.IDLE,
        Context(stock=5),
        StockChanged(3),
    )

    assert state == KioskState.IDLE
    assert ctx == Context(stock=3)
    assert effects == []


# Tesing that StockChanged event updates the stock in the context without changing the
# state, even if the kiosk is mid-session (e.g., CHECKING_TRAINING).
def test_stock_changed_updates_stock_mid_session_without_changing_state() -> None:
    state, ctx, effects = handle(
        KioskState.CHECKING_TRAINING,
        Context(stock=5),
        StockChanged(3),
    )

    assert state == KioskState.CHECKING_TRAINING
    assert ctx == Context(stock=3)
    assert effects == []


def test_refill_stock_from_out_of_stock() -> None:
    state, ctx, effects = handle(
        KioskState.OUT_OF_STOCK,
        Context(stock=0),
        StockChanged(5),
    )

    assert state == KioskState.IDLE
    assert ctx == Context(stock=5)
    assert effects == []
