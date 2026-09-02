"""L298N motor driver: GPIO control of the two wheel H-bridge channels.

The L298N module has two H-bridge channels. Each channel is controlled
by:
  * an ENABLE pin (PWM) — sets speed (0-100% duty);
  * two input pins (INx) — set direction:
      IN1=1, IN2=0 -> forward
      IN1=0, IN2=1 -> backward
      IN1=0, IN2=0 -> coast (brake is not used; we always stop via PWM=0)

``RPi.GPIO`` is imported lazily inside :meth:`MotorDriver.setup` so that
this module can be imported (and the rest of the app tested) on machines
without Raspberry Pi GPIO support.
"""

from . import constants


class MotorDriver:
    """Drives the left and right wheels through an L298N module."""

    def __init__(self, pins=None, pwm_frequency: int = constants.PWM_FREQUENCY_HZ):
        self._pins = pins or constants.GPIO_PINS
        self._pwm_frequency = pwm_frequency
        self._gpio = None
        self._pwm = {}
        self._setup_done = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Initialize GPIO pins and PWM channels. Call once before use."""
        if self._setup_done:
            return
        import RPi.GPIO as gpio  # lazy: not available off the Pi

        self._gpio = gpio
        gpio.setmode(gpio.BCM)
        gpio.setwarnings(False)

        for side, pins in self._pins.items():
            for role in ("in1", "in2", "in3", "in4"):
                if role in pins:
                    gpio.setup(pins[role], gpio.OUT, initial=gpio.LOW)
            if constants.ENABLE_SPEED_CONTROL:
                gpio.setup(pins["enable"], gpio.OUT, initial=gpio.LOW)
                pwm = gpio.PWM(pins["enable"], self._pwm_frequency)
                pwm.start(0.0)
                self._pwm[side] = pwm

        self._setup_done = True

    def cleanup(self) -> None:
        """Stop the motors and release all GPIO resources."""
        if not self._setup_done:
            return
        try:
            self.stop()
            for pwm in self._pwm.values():
                pwm.stop()
            for pins in self._pins.values():
                for role, pin in pins.items():
                    if role == "enable" and not constants.ENABLE_SPEED_CONTROL:
                        continue  # never configured, nothing to release
                    self._gpio.cleanup(pin)
        finally:
            self._pwm.clear()
            self._setup_done = False

    # ------------------------------------------------------------------
    # Motion primitives
    # ------------------------------------------------------------------

    def _set(self, left: float, right: float) -> None:
        """Set both wheels. Values are (direction, duty) pairs:
        +1 forward, -1 backward, 0 stopped; duty in 0.0-1.0."""
        if not self._setup_done:
            raise RuntimeError("MotorDriver.setup() has not been called")
        for side, (direction, duty) in (("left", left), ("right", right)):
            pins = self._pins[side]
            gpio = self._gpio
            if side == "left":
                fwd, rev = pins["in1"], pins["in2"]
            else:
                fwd, rev = pins["in3"], pins["in4"]
            if direction > 0:
                gpio.output(fwd, gpio.HIGH)
                gpio.output(rev, gpio.LOW)
            elif direction < 0:
                gpio.output(fwd, gpio.LOW)
                gpio.output(rev, gpio.HIGH)
            else:
                gpio.output(fwd, gpio.LOW)
                gpio.output(rev, gpio.LOW)
            if side in self._pwm:
                self._pwm[side].ChangeDutyCycle(max(0.0, min(1.0, duty)) * 100.0)

    def forward(self, speed: float = constants.DEFAULT_SPEED) -> None:
        """Drive both wheels forward at the given duty (0.0-1.0)."""
        self._set((1, speed), (1, speed))

    def backward(self, speed: float = constants.DEFAULT_SPEED) -> None:
        """Drive both wheels backward at the given duty (0.0-1.0)."""
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
        """Stop both wheels immediately (PWM off, inputs low)."""
        if not self._setup_done:
            return
        self._set((0, 0.0), (0, 0.0))
