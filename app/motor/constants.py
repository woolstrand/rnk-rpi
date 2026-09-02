"""Hardware constants for the rnk-rpi platform.

This is the single source of truth for every physical and electrical
parameter of the robot. Edit the values marked "CALIBRATE" to match your
actual hardware, then re-run the calibration steps described in the README.

The platform is a 3-wheeled chassis:
  * two driven wheels (left and right), each controlled independently by
    one H-bridge channel of an L298N motor driver module;
  * one free-rolling caster wheel, which needs no control.

GPIO pin numbers use the BCM (board) numbering scheme used by RPi.GPIO.
"""

import math

# ---------------------------------------------------------------------------
# Mechanical parameters (CALIBRATE these to your platform)
# ---------------------------------------------------------------------------

#: Diameter of one driven wheel, in centimeters.
#: Measure with a tape across the wheel (or circumference / pi).
WHEEL_DIAMETER_CM = 11.0

#: Center-to-center distance between the two driven wheels, in centimeters.
#: Measure between the wheel axles. Used for rotation calculations:
#: a full 360-degree turn makes each wheel travel one full circle of
#: radius WHEEL_SEPARATION_CM / 2.
WHEEL_SEPARATION_CM = 28.0

# ---------------------------------------------------------------------------
# Motor / drive parameters (CALIBRATE these to your motors)
# ---------------------------------------------------------------------------

#: No-load speed of one wheel motor in revolutions per minute,
#: measured at 100% PWM duty. Typical small DC gear motors run
#: 100-500 RPM; a common L298N demo motor is around 30-100 RPM.
MOTOR_RPM = 16.6

#: Default PWM duty cycle (0.0 - 1.0) used when executing commands.
#: Lower values are slower and quieter; higher values are faster but
#: draw more current. 0.5 is a safe starting point.
DEFAULT_SPEED = 0.5

# ---------------------------------------------------------------------------
# L298N wiring (BCM GPIO pin numbers)
# ---------------------------------------------------------------------------
#
# L298N module pinout (typical "L298N dual H-bridge" board):
#
#   ENA  -> PWM pin for the LEFT  wheel (enable / speed)
#   IN1  -> left wheel forward
#   IN2  -> left wheel backward
#   ENB  -> PWM pin for the RIGHT wheel (enable / speed)
#   IN3  -> right wheel forward
#   IN4  -> right wheel backward
#
# Power: motor supply (7-12 V) to the module's + terminal, and the
# module GROUND must be connected to the Raspberry Pi GROUND.
# See the wiring table in the README before connecting anything.

GPIO_PINS = {
    "left": {
        "enable": 12,  # ENA
        "in1": 17,     # forward
        "in2": 27,     # backward
    },
    "right": {
        "enable": 13,  # ENB
        "in3": 22,     # forward
        "in4": 23,     # backward
    },
}

#: PWM frequency in Hz. 1000 Hz is inaudible and smooth for DC motors.
PWM_FREQUENCY_HZ = 1000

#: Whether the driver should actively drive ENA/ENB for PWM speed control.
#: Set to False if ENA/ENB are hard-wired (jumpered) to a fixed voltage on
#: the L298N board itself: the Pi's GPIO pins are then left unconfigured
#: so they never contend with the jumper's fixed level. Set to True only
#: after removing the jumpers and wiring ENA/ENB to the pins above.
ENABLE_SPEED_CONTROL = False

# ---------------------------------------------------------------------------
# Command limits (safety rails for the public API)
# ---------------------------------------------------------------------------

#: Maximum single movement length in centimeters.
MAX_MOVE_CM = 1000.0

#: Maximum single rotation in degrees.
MAX_ROTATE_DEG = 3600.0

#: Maximum number of commands allowed in the queue at once.
MAX_QUEUE_SIZE = 100

#: How often (seconds) the worker thread checks for a stop request
#: while a command is running. Smaller = more responsive stop,
#: slightly more CPU.
STOP_CHECK_INTERVAL_S = 0.05


def wheel_speed_cm_per_s(speed: float = DEFAULT_SPEED) -> float:
    """Linear speed of one wheel in cm/s at the given PWM duty.

    wheel_speed = RPM * duty * (pi * diameter) / 60
    """
    return MOTOR_RPM * speed * (math.pi * WHEEL_DIAMETER_CM) / 60.0
