"""L298N motor driver: GPIO control of the two wheel H-bridge channels.

Each motor is wired directly to two direction pins on the L298N (IN1/IN2
for the left motor, IN3/IN4 for the right motor). ENA/ENB are not driven
by the Pi: speed is controlled by applying PWM directly to whichever
direction pin is active for the current motion (forward or backward),
instead of the enable pin. Direction is selected simply by choosing which
of the two pins receives the PWM signal, while the other stays at 0% duty
(effectively LOW):
  * forward:  IN1/IN3 = PWM(duty), IN2/IN4 = 0%
  * backward: IN1/IN3 = 0%,        IN2/IN4 = PWM(duty)
  * stopped:  both pins = 0%

Each motor also has an encoder. Only one trigger per motor is needed
since the commanded direction is already known; the driver counts rising
edges on that pin to track how far each wheel has turned.

``RPi.GPIO`` is imported lazily inside :meth:`MotorDriver.setup` so that
this module can be imported (and the rest of the app tested) on machines
without Raspberry Pi GPIO support.
"""

import threading

from . import constants


class MotorDriver:
    """Drives the left and right wheels through an L298N module."""

    def __init__(self, pins=None, pwm_frequency: int = constants.PWM_FREQUENCY_HZ):
        self._pins = pins or constants.GPIO_PINS
        self._pwm_frequency = pwm_frequency
        self._gpio = None
        self._pwm = {}
        self._setup_done = False
        self._ticks_lock = threading.Lock()
        self._ticks = {"left": 0, "right": 0}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Initialize GPIO pins, PWM channels and encoder inputs. Call once before use."""
        if self._setup_done:
            return
        import RPi.GPIO as gpio  # lazy: not available off the Pi

        self._gpio = gpio
        gpio.setmode(gpio.BCM)
        gpio.setwarnings(False)

        for side, pins in self._pins.items():
            fwd_role, rev_role = self._direction_roles(side)
            for role in (fwd_role, rev_role):
                pin = pins[role]
                gpio.setup(pin, gpio.OUT, initial=gpio.LOW)
                pwm = gpio.PWM(pin, self._pwm_frequency)
                pwm.start(0.0)
                self._pwm[(side, role)] = pwm

            encoder_pin = pins["encoder"]
            gpio.setup(encoder_pin, gpio.IN, pull_up_down=gpio.PUD_UP)
            gpio.add_event_detect(
                encoder_pin,
                gpio.RISING,
                callback=self._make_tick_callback(side),
                bouncetime=1,
            )

        self._setup_done = True

    def cleanup(self) -> None:
        """Stop the motors and release all GPIO resources."""
        if not self._setup_done:
            return
        try:
            self.stop()
            for pwm in self._pwm.values():
                pwm.stop()
            for side, pins in self._pins.items():
                fwd_role, rev_role = self._direction_roles(side)
                for role in (fwd_role, rev_role):
                    self._gpio.cleanup(pins[role])
                self._gpio.remove_event_detect(pins["encoder"])
                self._gpio.cleanup(pins["encoder"])
        finally:
            self._pwm.clear()
            self._setup_done = False

    # ------------------------------------------------------------------
    # Motion primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _direction_roles(side: str):
        return ("in1", "in2") if side == "left" else ("in3", "in4")

    def _set(self, left: float, right: float) -> None:
        """Set both wheels. Values are (direction, duty) pairs:
        +1 forward, -1 backward, 0 stopped; duty in 0.0-1.0."""
        if not self._setup_done:
            raise RuntimeError("MotorDriver.setup() has not been called")
        for side, (direction, duty) in (("left", left), ("right", right)):
            fwd_role, rev_role = self._direction_roles(side)
            if constants.INVERT_DIRECTION:
                direction = -direction
            duty_pct = max(0.0, min(1.0, duty)) * 100.0
            if direction > 0:
                self._pwm[(side, fwd_role)].ChangeDutyCycle(duty_pct)
                self._pwm[(side, rev_role)].ChangeDutyCycle(0.0)
            elif direction < 0:
                self._pwm[(side, fwd_role)].ChangeDutyCycle(0.0)
                self._pwm[(side, rev_role)].ChangeDutyCycle(duty_pct)
            else:
                self._pwm[(side, fwd_role)].ChangeDutyCycle(0.0)
                self._pwm[(side, rev_role)].ChangeDutyCycle(0.0)

    def forward(self, speed: float = constants.DEFAULT_SPEED) -> None:
        """Drive both wheels forward at the given duty (0.0-1.0]."""
        self._set((1, speed), (1, speed))

    def backward(self, speed: float = constants.DEFAULT_SPEED) -> None:
        """Drive both wheels backward at the given duty (0.0-1.0]."""
        self._set((-1, speed), (-1, speed))

    def left(self, speed: float = constants.DEFAULT_SPEED) -> None:
        """Pivot in place clockwise (viewed from above):
        left wheel forward, right wheel backward."""
        self._set((1, speed), (-1, speed))

    def right(self, speed: float = constants.DEFAULT_SPEED) -> None:
        """Pivot in place counter-clockwise:
        left wheel backward, right wheel forward."""
        self._set((-1, speed), (1, speed))

    def stop(self) -> None:
        """Stop both wheels immediately (PWM off)."""
        if not self._setup_done:
            return
        self._set((0, 0.0), (0, 0.0))

    def drive(
        self,
        left_direction: int,
        left_speed: float,
        right_direction: int,
        right_speed: float,
    ) -> None:
        """Command each wheel's direction/duty independently.

        Used by the scheduler's closed-loop trajectory correction to
        rebalance duty cycle between the wheels without changing the
        overall commanded direction.
        """
        self._set((left_direction, left_speed), (right_direction, right_speed))

    # ------------------------------------------------------------------
    # Encoders
    # ------------------------------------------------------------------

    def _make_tick_callback(self, side: str):
        def _callback(_channel):
            with self._ticks_lock:
                self._ticks[side] += 1

        return _callback

    def reset_ticks(self) -> None:
        """Zero both wheels' accumulated encoder tick counts."""
        with self._ticks_lock:
            self._ticks = {"left": 0, "right": 0}

    def get_ticks(self) -> dict:
        """Return a snapshot of accumulated encoder ticks per wheel."""
        with self._ticks_lock:
            return dict(self._ticks)
