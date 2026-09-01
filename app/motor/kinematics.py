"""Kinematics: convert command values (cm, degrees) into motor run times.

Pure functions only — no I/O, no GPIO. This keeps the math trivially
testable on any machine.

Conventions:
  * ``move`` values are distances in centimeters. Positive = forward.
  * ``rotate`` values are angles in degrees. Positive = clockwise
    (viewed from above) = left wheel forward, right wheel backward.

Both wheels of a command run at DEFAULT_SPEED, so the conversions below
are based on the linear speed of a single wheel at that duty.
"""

import math

from . import constants


def move_time_s(distance_cm: float) -> float:
    """Seconds both wheels must run (same direction) to travel ``distance_cm``.

    Both wheels move together, so the platform travels exactly the
    distance each wheel travels.
    """
    if distance_cm < 0:
        raise ValueError("distance_cm must be non-negative")
    speed = constants.wheel_speed_cm_per_s()
    if speed <= 0:
        raise ValueError("wheel speed is zero; check MOTOR_RPM / DEFAULT_SPEED")
    return distance_cm / speed


def rotate_time_s(angle_deg: float) -> float:
    """Seconds the wheels must run in opposite directions to rotate ``angle_deg``.

    During a pivot the platform rotates about the midpoint between the
    driven wheels, so each wheel traces an arc of radius
    WHEEL_SEPARATION_CM / 2. A full 360-degree turn therefore makes each
    wheel travel one full circle of that radius:

        arc length per full turn = pi * WHEEL_SEPARATION_CM
    """
    if angle_deg < 0:
        raise ValueError("angle_deg must be non-negative")
    speed = constants.wheel_speed_cm_per_s()
    if speed <= 0:
        raise ValueError("wheel speed is zero; check MOTOR_RPM / DEFAULT_SPEED")
    circumference = math.pi * constants.WHEEL_SEPARATION_CM
    return (angle_deg / 360.0) * circumference / speed
