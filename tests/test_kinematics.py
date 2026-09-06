"""Tests for the cm/deg -> encoder tick conversions in app.motor.kinematics."""

import math

import pytest

from app.motor import constants, kinematics


def test_wheel_ticks_per_cm():
    ticks_per_rev = constants.ENCODER_TICKS_PER_MOTOR_REV * constants.GEAR_RATIO
    expected = ticks_per_rev / (math.pi * constants.WHEEL_DIAMETER_CM)
    assert constants.wheel_ticks_per_cm() == pytest.approx(expected)


def test_move_ticks():
    ticks_per_cm = constants.wheel_ticks_per_cm()
    assert kinematics.move_ticks(10.0) == round(10.0 * ticks_per_cm)
    assert kinematics.move_ticks(0.0) == 0


def test_move_ticks_ignores_sign():
    assert kinematics.move_ticks(-10.0) == kinematics.move_ticks(10.0)


def test_rotate_ticks():
    ticks_per_cm = constants.wheel_ticks_per_cm()
    circumference = math.pi * constants.WHEEL_SEPARATION_CM
    # 90 degrees is a quarter of a full turn; each wheel travels
    # a quarter of the separation circumference.
    expected = round((90.0 / 360.0) * circumference * ticks_per_cm)
    assert kinematics.rotate_ticks(90.0) == expected
    # A full turn: each wheel travels one full circle of radius separation/2.
    assert kinematics.rotate_ticks(360.0) == round(circumference * ticks_per_cm)


def test_rotate_ticks_ignores_sign():
    assert kinematics.rotate_ticks(-90.0) == kinematics.rotate_ticks(90.0)
