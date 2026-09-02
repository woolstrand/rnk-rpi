"""Kinematics: convert command values (cm, degrees) into motor run times.

Pure functions only — no I/O, no GPIO. This keeps the math trivially
testable on any machine.

Conventions:
  * ``move`` values are distances in centimeters. Positive = forward,
    negative = backward. The sign only picks the direction; duration is
    based on the magnitude.
  * ``rotate`` values are angles in degrees. Positive = clockwise
    (viewed from above) = left wheel forward, right wheel backward.
    Negative = counter-clockwise = left wheel backward, right wheel
    forward. Duration is based on the magnitude.

Both wheels of a command run at DEFAULT_SPEED, so the conversions below
are based on the linear speed of a single wheel at that duty.
"""

import math

from . import constants


def move_time_s(distance_cm: float) -> float:
    """Seconds both wheels must run (same direction) to travel ``distance_cm``.

    Both wheels move together, so the platform travels exactly the
    distance each wheel travels. The sign of ``distance_cm`` is ignored;
    the caller decides forward vs backward.
    """
    speed = constants.wheel_speed_cm_per_s()
    if speed <= 0:
        raise ValueError("wheel speed is zero; check MOTOR_RPM / DEFAULT_SPEED")
    return abs(distance_cm) / speed


def rotate_time_s(angle_deg: float) -> float:
    """Seconds the wheels must run in opposite directions to rotate ``angle_deg``.

    During a pivot the platform rotates about the midpoint between the
    driven wheels, so each wheel traces an arc of radius
    WHEEL_SEPARATION_CM / 2. A full 360-degree turn therefore makes each
    wheel travel one full circle of that radius:

        arc length per full turn = pi * WHEEL_SEPARATION_CM

    The sign of ``angle_deg`` is ignored; the caller decides clockwise vs
    counter-clockwise.
    """
    speed = constants.wheel_speed_cm_per_s()
    if speed <= 0:
        raise ValueError("wheel speed is zero; check MOTOR_RPM / DEFAULT_SPEED")
    circumference = math.pi * constants.WHEEL_SEPARATION_CM
    return (abs(angle_deg) / 360.0) * circumference / speed
