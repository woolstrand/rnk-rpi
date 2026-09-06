"""Kinematics: convert command values (cm, degrees) into encoder tick counts.

Pure functions only — no I/O, no GPIO. This keeps the math trivially
testable on any machine.

Conventions:
  * ``move`` values are distances in centimeters. Positive = forward,
    negative = backward. The sign only picks the direction; the tick
    count is based on the magnitude.
  * ``rotate`` values are angles in degrees. Positive = clockwise
    (viewed from above) = left wheel forward, right wheel backward.
    Negative = counter-clockwise = left wheel backward, right wheel
    forward. The tick count is based on the magnitude.

Each driven wheel has its own encoder (one trigger per motor, since the
commanded direction is already known), producing
``ENCODER_TICKS_PER_MOTOR_REV * GEAR_RATIO`` ticks per wheel revolution.
"""

import math

from . import constants


def move_ticks(distance_cm: float) -> int:
    """Encoder ticks each wheel must accumulate to travel ``distance_cm``.

    Both wheels move together, so the platform travels exactly the
    distance each wheel travels. The sign of ``distance_cm`` is ignored;
    the caller decides forward vs backward.
    """
    return round(abs(distance_cm) * constants.wheel_ticks_per_cm())


def rotate_ticks(angle_deg: float) -> int:
    """Encoder ticks each wheel must accumulate to rotate ``angle_deg``.

    During a pivot the platform rotates about the midpoint between the
    driven wheels, so each wheel traces an arc of radius
    WHEEL_SEPARATION_CM / 2. A full 360-degree turn therefore makes each
    wheel travel one full circle of that radius:

        arc length per full turn = pi * WHEEL_SEPARATION_CM

    The sign of ``angle_deg`` is ignored; the caller decides clockwise vs
    counter-clockwise.
    """
    circumference = math.pi * constants.WHEEL_SEPARATION_CM
    arc_cm = (abs(angle_deg) / 360.0) * circumference
    return round(arc_cm * constants.wheel_ticks_per_cm())
