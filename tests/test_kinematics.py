"""Tests for the cm/deg -> seconds conversions in app.motor.kinematics."""

import math

import pytest

from app.motor import constants, kinematics


def test_wheel_speed():
    expected = constants.MOTOR_RPM * constants.DEFAULT_SPEED * (
        math.pi * constants.WHEEL_DIAMETER_CM
    ) / 60.0
    assert kinematics.wheel_speed_cm_per_s() == pytest.approx(expected)
    assert constants.wheel_speed_cm_per_s(1.0) == pytest.approx(
        constants.MOTOR_RPM * math.pi * constants.WHEEL_DIAMETER_CM / 60.0
    )


def test_move_time_s():
    speed = constants.wheel_speed_cm_per_s()
    assert kinematics.move_time_s(10.0) == pytest.approx(10.0 / speed)
    assert kinematics.move_time_s(0.0) == 0.0


def test_move_time_rejects_negative():
    with pytest.raises(ValueError):
        kinematics.move_time_s(-1.0)


def test_rotate_time_s():
    speed = constants.wheel_speed_cm_per_s()
    circumference = math.pi * constants.WHEEL_SEPARATION_CM
    # 90 degrees is a quarter of a full turn; each wheel travels
    # a quarter of the separation circumference.
    expected = (90.0 / 360.0) * circumference / speed
    assert kinematics.rotate_time_s(90.0) == pytest.approx(expected)
    # A full turn: each wheel travels one full circle of radius separation/2.
    assert kinematics.rotate_time_s(360.0) == pytest.approx(circumference / speed)


def test_rotate_time_rejects_negative():
    with pytest.raises(ValueError):
        kinematics.rotate_time_s(-5.0)


def test_zero_speed_raises():
    original = constants.MOTOR_RPM
    constants.MOTOR_RPM = 0.0
    try:
        with pytest.raises(ValueError):
            kinematics.move_time_s(1.0)
        with pytest.raises(ValueError):
            kinematics.rotate_time_s(10.0)
    finally:
        constants.MOTOR_RPM = original
