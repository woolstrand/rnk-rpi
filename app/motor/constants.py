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

#: Encoder ticks per one revolution of the *motor* shaft (before the
#: gearbox reduction). Each driven wheel has one encoder trigger, which is
#: enough since the commanded direction is already known.
ENCODER_TICKS_PER_MOTOR_REV = 11

#: Gearbox reduction ratio between the motor shaft and the wheel axle.
#: One wheel revolution corresponds to GEAR_RATIO motor revolutions.
GEAR_RATIO = 21.3

#: Default PWM duty cycle (0.0 - 1.0] used when executing commands.
#: Lower values are slower and quieter; higher values are faster but
#: draw more current.
DEFAULT_SPEED = 0.4

# ---------------------------------------------------------------------------
# L298N wiring (BCM GPIO pin numbers)
# ---------------------------------------------------------------------------
#
# L298N module pinout (typical "L298N dual H-bridge" board):
#
#   IN1  -> left wheel forward (PWM speed + direction)
#   IN2  -> left wheel backward (PWM speed + direction)
#   IN3  -> right wheel forward (PWM speed + direction)
#   IN4  -> right wheel backward (PWM speed + direction)
#
# Each motor now has an encoder (one trigger per motor is enough since the
# commanded direction is already known):
#
#   left encoder  -> signal input, counts ticks while the left motor spins
#   right encoder -> signal input, counts ticks while the right motor spins
#
# ENA/ENB are no longer driven by the Pi: speed is controlled by applying
# PWM directly to whichever direction pin (IN1/IN2/IN3/IN4) is active,
# instead of the enable pin.
#
# Power: motor supply (7-12 V) to the module's + terminal, and the
# module GROUND must be connected to the Raspberry Pi GROUND.
# See the wiring table in the README before connecting anything.

GPIO_PINS = {
    "left": {
        "in1": 17,      # forward (PWM)
        "in2": 27,      # backward (PWM)
        "encoder": 5,   # encoder signal
    },
    "right": {
        "in3": 22,      # forward (PWM)
        "in4": 23,      # backward (PWM)
        "encoder": 6,   # encoder signal
    },
}

#: PWM frequency in Hz. 1000 Hz is inaudible and smooth for DC motors.
PWM_FREQUENCY_HZ = 1000

#: Flip forward/backward for both wheels. Set to True when the wiring
#: (motor leads or IN1/IN2 / IN3/IN4 pairs) makes "forward" commands drive
#: the platform backward. Fixes direction without touching the pin map.
INVERT_DIRECTION = True

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


def wheel_ticks_per_revolution() -> float:
    """Encoder ticks produced by one full revolution of the wheel."""
    return ENCODER_TICKS_PER_MOTOR_REV * GEAR_RATIO


def wheel_ticks_per_cm() -> float:
    """Encoder ticks produced per centimeter of wheel travel."""
    return wheel_ticks_per_revolution() / (math.pi * WHEEL_DIAMETER_CM)
