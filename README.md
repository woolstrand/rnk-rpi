# rnk-rpi

RPi part of the infamous ROBOT NA KOLYOSEEKAKH project.

A Raspberry Pi service that controls a **motorized 3-wheeled platform**
(2 independently driven wheels + 1 free-rolling caster wheel) through an
**L298N dual H-bridge motor driver module**, and acts as a **control proxy**
for a separate **ONVIF/RTSP IP camera** (pan/tilt/zoom + JPEG snapshots).

The service exposes a small HTTP API:

| Method | Path                    | Description                                                  |
|--------|-------------------------|---------------------------------------------------------------|
| POST   | `/rnk/schedule`         | Enqueue a command: `{"move": <cm>}` or `{"rotate": <deg>}`    |
| GET    | `/rnk/schedule`         | Inspect the queue (running + pending commands)                |
| POST   | `/rnk/stop`             | Halt the motors immediately and clear the queue                |
| POST   | `/rnk/camera/ptz/absolute` | Move the camera to an absolute pan/tilt/zoom position       |
| POST   | `/rnk/camera/ptz/relative` | Move the camera by a pan/tilt/zoom delta                    |
| POST   | `/rnk/camera/ptz/stop`  | Stop any in-progress camera movement                           |
| POST   | `/rnk/camera/home`      | Reset the camera to its home/center position                   |
| GET    | `/rnk/camera/status`    | Current camera PTZ position + capabilities                     |
| GET    | `/rnk/camera/snapshot`  | Capture a single JPEG frame from the camera's RTSP stream       |

Commands are executed **strictly one by one**, in the order received, by a
single worker thread. After every command the motors are stopped, so the
platform is never left moving on its own.

## How it works

```
HTTP client ──> Flask API (POST /rnk/schedule)
                    │ enqueue
                    ▼
              CommandScheduler (thread-safe queue)
                    │ one command at a time
                    ▼
              MotorDriver (RPi.GPIO: PWM + direction pins)
                    │
                    ▼
              L298N module ──> left wheel motor / right wheel motor
```

* **`move`** — both wheels run in the same direction for a duration
  computed from the distance (cm). Positive = forward.
* **`rotate`** — wheels run in opposite directions (pivot in place) for a
  duration computed from the angle (degrees). Positive = clockwise
  (viewed from above).

All physical parameters (wheel diameter, wheel separation, motor RPM,
PWM duty, GPIO pins, limits) live in **[`app/motor/constants.py`](app/motor/constants.py)** —
see [Calibration](#calibration) before first use.

## Hardware

* Raspberry Pi (any model with GPIO; tested against Raspberry Pi OS)
* L298N dual H-bridge motor driver module
* 2× DC gear motors (one per driven wheel)
* Motor power supply: **7–12 V** (e.g. 2× AA NiMH pack or a 7.4 V Li-ion
  pack) — **do not** power the motors from the Pi's 5 V rail
* 3-wheeled chassis with a free-rolling caster wheel
* An ONVIF-compatible PTZ IP camera on the same network, reachable from the
  Pi over HTTP (ONVIF control) and RTSP (video) — connected over Wi-Fi/PoE,
  not wired to the Pi's GPIO

### Wiring

| L298N pin | Raspberry Pi (BCM GPIO) | Purpose                    |
|-----------|-------------------------|----------------------------|
| ENA       | 12                      | left wheel speed (PWM)     |
| IN1       | 17                      | left wheel forward         |
| IN2       | 27                      | left wheel backward        |
| ENB       | 13                      | right wheel speed (PWM)    |
| IN3       | 22                      | right wheel forward        |
| IN4       | 23                      | right wheel backward       |
| GND       | any GND pin             | **must** be connected      |
| + (motor supply) | 7–12 V battery   | **not** the Pi's 5 V       |

Motor outputs: `OUT1/OUT2` → left motor, `OUT3/OUT4` → right motor.

> ⚠️ **Shared ground is mandatory.** The battery GND must be connected to
> the Pi GND, otherwise the GPIO signals have no common reference and the
> motors will behave erratically (or damage the Pi).
>
> ⚠️ If your L298N board's pin layout differs, update `GPIO_PINS` in
> `app/motor/constants.py` to match.

## Setup & deployment (on the Raspberry Pi)

```bash
# 1. Get the code
git clone <repo-url> rnk-rpi
cd rnk-rpi

# 2. One-shot setup:
#    - apt deps (python3-venv, python3-pip)
#    - .venv + pip install -r requirements.txt
#    - adds your user to the "gpio" group (needed for /dev/gpiomem)
#    - installs, enables and starts the rnk-rpi systemd service
./scripts/setup.sh
```

The service binds to `0.0.0.0:5000` (configurable in `app/config.py`), so
you can command the robot from any device on the local network.

`setup.sh` also installs `ffmpeg` (used to grab camera snapshots) and
creates a `.env` file from `.env.example` if one doesn't already exist —
edit it with the camera's real IP address and credentials (see
[Camera control](#camera-control)) and restart the service.

### Service management

`setup.sh` also installs a sudoers drop-in that lets your user run the
service's `systemctl`/`journalctl` commands **without a password prompt**.
Use the `scripts/rnk-rpi` wrapper for this:

```bash
./scripts/rnk-rpi status          # is it running?
./scripts/rnk-rpi logs            # live logs (Ctrl-C to stop)
./scripts/rnk-rpi logs-once       # last 50 log lines
./scripts/rnk-rpi restart         # after editing code/constants
./scripts/rnk-rpi stop            # stop the service (motors halt)
```

(Plain `systemctl`/`sudo systemctl` still work too, but may prompt for a
password since they aren't covered by the sudoers rule.)

The service restarts automatically on crash (`Restart=always`) and starts
automatically on boot (`systemctl enable`, done by `setup.sh`). On any
shutdown the driver is cleaned up, so the motors are never left energized.

## API reference

### `POST /rnk/schedule`

Enqueue a motion command. The body must be a JSON object with **exactly
one** of the two keys:

```bash
# Move forward 70 cm
curl -X POST http://<pi-ip>:5000/rnk/schedule \
  -H 'Content-Type: application/json' \
  -d '{"move": 70}'

# Rotate 35 degrees clockwise (in place)
curl -X POST http://<pi-ip>:5000/rnk/schedule \
  -H 'Content-Type: application/json' \
  -d '{"rotate": 35}'
```

Response `202`:

```json
{
  "status": "queued",
  "command": {"kind": "move", "value": 70.0},
  "position": 1,
  "queue_size": 1
}
```

Validation (all return `400` with an `error` message):

* both `move` and `rotate` present, or neither
* non-numeric, non-finite, or non-positive values
* `move` above `MAX_MOVE_CM` (default 1000 cm)
* `rotate` above `MAX_ROTATE_DEG` (default 3600 deg)

A `503` is returned when the queue is full (`MAX_QUEUE_SIZE`, default 100).

### `GET /rnk/schedule`

```bash
curl http://<pi-ip>:5000/rnk/schedule
```

```json
{
  "busy": true,
  "queue_size": 2,
  "queue": [
    {"kind": "move", "value": 70.0, "added_at": 1756680000.123, "state": "running"},
    {"kind": "rotate", "value": 35.0, "added_at": 1756680001.456, "state": "queued"}
  ]
}
```

### `POST /rnk/stop`

```bash
curl -X POST http://<pi-ip>:5000/rnk/stop
```

Stops the currently running command within ~50 ms and discards all pending
commands. Response: `{"status": "stopped", "cleared": 2}`.

## Camera control

The Pi acts as a **control proxy** for a separate ONVIF/RTSP IP camera: it
is not wired to the Pi at all, just reachable on the same network. The
service talks **ONVIF** (SOAP over HTTP) to the camera for pan/tilt/zoom
control, and shells out to **ffmpeg** to grab single JPEG frames from its
**RTSP** video stream.

### Configuration (`.env`)

The camera's IP address and credentials are read from a `.env` file at the
repo root (never committed — see `.gitignore`). Copy the template and edit
it:

```bash
cp .env.example .env
```

| Variable                 | Default     | Description                                      |
|---------------------------|-------------|---------------------------------------------------|
| `CAMERA_IP`               | *(required)*| Camera's IP address. If unset, all `/rnk/camera/*` endpoints return `503`. |
| `CAMERA_ONVIF_PORT`       | `80`        | ONVIF (SOAP/HTTP) port                             |
| `CAMERA_USERNAME`         | *(empty)*   | ONVIF/RTSP username                                |
| `CAMERA_PASSWORD`         | *(empty)*   | ONVIF/RTSP password                                |
| `CAMERA_ONVIF_TIMEOUT_S`  | `5`         | Timeout for ONVIF SOAP calls                       |
| `CAMERA_ONVIF_WSDL_DIR`   | *(auto-detected)* | Path to onvif-zeep's WSDL folder; only needed if auto-detection fails (see Troubleshooting) |
| `CAMERA_RTSP_URL`         | *(built from the vars below)* | Full RTSP URL override, e.g. `rtsp://user:pass@ip:554/stream1` |
| `CAMERA_RTSP_PORT`        | `554`       | RTSP port (used only if `CAMERA_RTSP_URL` is unset)|
| `CAMERA_RTSP_PATH`        | `stream1`   | RTSP path (used only if `CAMERA_RTSP_URL` is unset)|

After editing `.env`: `./scripts/rnk-rpi restart`.

### Pan/tilt/zoom coordinates

Pan/tilt/zoom use ONVIF's normalized **generic PTZ space**, since every
ONVIF PTZ camera supports it (camera-specific degree/mm spaces often
aren't exposed):

* **pan**, **tilt**: `-1.0` to `1.0` (one extreme to the other; `0.0` is center)
* **zoom**: `0.0` (wide) to `1.0` (tele)

Whether **absolute** moves are supported depends on the camera; if not,
use **relative** moves instead (deltas in the same `-1.0..1.0` range).
Check `GET /rnk/camera/status` → `capabilities` to see what your camera
supports. A `501` is returned if you call an unsupported operation.

### `POST /rnk/camera/ptz/absolute`

```bash
curl -X POST http://<pi-ip>:5000/rnk/camera/ptz/absolute \
  -H 'Content-Type: application/json' \
  -d '{"pan": 0.5, "tilt": -0.2, "zoom": 0.3}'
```

`zoom` is optional. Response `200`: `{"status": "ok", "pan": 0.5, "tilt": -0.2, "zoom": 0.3}`.

### `POST /rnk/camera/ptz/relative`

Same body shape, but values are **deltas** from the current position:

```bash
curl -X POST http://<pi-ip>:5000/rnk/camera/ptz/relative \
  -H 'Content-Type: application/json' \
  -d '{"pan": -0.1, "tilt": 0.1}'
```

### `POST /rnk/camera/ptz/stop`

```bash
curl -X POST http://<pi-ip>:5000/rnk/camera/ptz/stop
```

Stops any in-progress pan/tilt/zoom movement.

### `POST /rnk/camera/home`

```bash
curl -X POST http://<pi-ip>:5000/rnk/camera/home
```

Resets pan/tilt to the camera's home/central position: uses the ONVIF
`GotoHomePosition` preset if the camera has one, otherwise falls back to
an absolute move to pan=0/tilt=0. Returns `501` if neither is supported.

### `GET /rnk/camera/status`

```bash
curl http://<pi-ip>:5000/rnk/camera/status
```

```json
{
  "pan": 0.5,
  "tilt": -0.2,
  "zoom": 0.3,
  "moving": false,
  "capabilities": {"absolute": true, "relative": true, "home": true}
}
```

### `GET /rnk/camera/snapshot`

Captures a single JPEG frame from the RTSP stream.

```bash
# Full resolution
curl http://<pi-ip>:5000/rnk/camera/snapshot -o frame.jpg

# Scaled down to 640x480
curl 'http://<pi-ip>:5000/rnk/camera/snapshot?scaled=true' -o frame.jpg
```

Returns `200` with `Content-Type: image/jpeg` on success, or `502` (JSON
error body) if ffmpeg couldn't pull a frame (camera offline, wrong
credentials, stream timeout, etc).

All `/rnk/camera/*` endpoints return `503` if no camera is configured
(`CAMERA_IP` unset in `.env`).

### Troubleshooting

A `502 camera communication failed` means the request reached the service
but the ONVIF/RTSP call to the camera itself failed. The API only returns
a generic message (to avoid leaking the camera URL/credentials in an HTTP
response), but the full exception is logged — check it on the Pi:

```bash
./scripts/rnk-rpi logs-once   # last 50 lines
./scripts/rnk-rpi logs        # live tail
```

To check ONVIF login/reachability directly, independent of the Flask app
(run on the Pi, inside its venv):

```bash
.venv/bin/python -c "
from onvif import ONVIFCamera
cam = ONVIFCamera('<camera-ip>', <onvif-port>, '<username>', '<password>')
print(cam.devicemgmt.GetDeviceInformation())
"
```

* `onvif.exceptions.ONVIFError: ... No such file: .../wsdl/devicemgmt.wsdl`
  → onvif-zeep's install script computes where to copy its `wsdl/` folder
  itself (via `distutils`/`sysconfig`) instead of shipping it as normal
  package data, and that computation is unreliable — notably, on
  Debian-based distros (Raspberry Pi OS included) it can report the wrong
  Python version (e.g. copying to a `python3.4` directory inside a venv
  that's actually running `python3.13`). The app auto-detects this at
  startup by searching every `lib/python*/site-packages/wsdl` under the
  venv, so this should now resolve itself. If it still doesn't, locate the
  files and point the app at them manually:
  ```bash
  find .venv -iname devicemgmt.wsdl
  ```
  then set `CAMERA_ONVIF_WSDL_DIR` in `.env` to the directory that file is
  in (not the file itself), and `./scripts/rnk-rpi restart`. To test
  manually, pass it as the 5th argument: `ONVIFCamera(ip, port, user,
  password, '<that-directory>')`.
* `Fault: Sender not Authorized` / similar → wrong username or password.
* Connection refused/timeout → wrong IP or ONVIF port (many cameras use
  `8080`, `2020`, or `8899`, not `80` — check the camera's own web UI/ONVIF
  settings), or a firewall blocking it.
* Auth failing with credentials you've verified are correct → check for
  **clock skew**: ONVIF's WS-Security scheme timestamps every request and
  cameras commonly reject requests if the Pi's and camera's clocks differ
  by more than a few minutes (`timedatectl` on the Pi; make sure NTP is
  enabled).

To check the RTSP stream/credentials separately (snapshot uses a
different code path than PTZ):

```bash
ffmpeg -loglevel error -rtsp_transport tcp \
  -i 'rtsp://<username>:<password>@<camera-ip>:554/<path>' \
  -frames:v 1 -f image2 -vcodec mjpeg test.jpg
```

If that produces a valid `test.jpg`, the RTSP side is fine even if ONVIF
PTZ isn't (and vice versa) — they're independent connections/credentials
on many cameras.

## Calibration

The constants in [`app/motor/constants.py`](app/motor/constants.py) ship
with **placeholder values**. Before trusting the robot, calibrate:

1. **`WHEEL_DIAMETER_CM`** — measure the wheel diameter (or measure the
   circumference with a tape and divide by π).
2. **`WHEEL_SEPARATION_CM`** — measure center-to-center distance between
   the two driven wheel axles.
3. **`MOTOR_RPM`** — the no-load RPM of your motor at full power. If the
   spec is unknown: run `{"move": 100}` with the platform on stands,
   time it with a stopwatch, and compute
   `RPM = distance_cm / time_s * 60 / (pi * WHEEL_DIAMETER_CM) / DEFAULT_SPEED`.
4. **`DEFAULT_SPEED`** — start at `0.5`. Raise for more speed, lower for
   more control / less current draw.
5. **Verify**: command a 100 cm move, measure the actual distance, and
   adjust `MOTOR_RPM` (or `DEFAULT_SPEED`) until the error is within ~10%.
   Do the same for a 360° rotation.

After editing constants: `./scripts/rnk-rpi restart`.

## Project layout

```
├── main.py                  # entry point: starts scheduler, runs Flask
├── app/
│   ├── __init__.py          # create_app() factory
│   ├── config.py            # HOST / PORT
│   ├── api/schedule.py      # the /rnk endpoints
│   ├── scheduler.py         # queue + single worker thread + stop
│   └── motor/
│       ├── constants.py     # ← all hardware parameters (calibrate here)
│       ├── driver.py        # L298N GPIO control (PWM + direction)
│       └── kinematics.py    # cm/deg → seconds conversions
├── scripts/
│   ├── setup.sh             # one-shot Pi setup (deps, venv, systemd, sudoers)
│   ├── rnk-rpi              # passwordless start/stop/restart/status/logs wrapper
│   ├── rnk-rpi.service      # systemd unit template
│   └── rnk-rpi.sudoers      # sudoers drop-in template (passwordless systemctl)
├── tests/                   # pytest suite (runs without hardware)
└── requirements.txt
```

## Running the tests (any machine, no Pi required)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/pytest
```

The tests use a fake motor driver, so no GPIO hardware is needed.

## Troubleshooting

* **`ImportError: RPi.GPIO` on the Pi** — make sure you run inside the
  project's `.venv` (setup.sh does this for the service).
* **`PermissionError` / `OSError` on `/dev/gpiomem`** — your user must be
  in the `gpio` group: `sudo usermod -aG gpio $USER`, then **log out and
  back in**. (The systemd service already runs with `SupplementaryGroups=gpio`.)
* **Motors don't move but no error** — check the battery is connected and
  the shared ground; check `GPIO_PINS` matches your board; verify with
  `journalctl -u rnk-rpi -f` that commands are being executed.
* **Motors spin the wrong way** — swap the two motor leads on the L298N
  output, or swap `in1`/`in2` (and `in3`/`in4`) in `GPIO_PINS`.
* **Robot drifts sideways on `move`** — the two motors are not matched.
  Fine-tune by adding per-wheel speed factors in `app/motor/driver.py`
  (e.g. scale the right wheel duty by 0.95) until it runs straight.
* **`RPi.GPIO` deprecation warnings** — RPi.GPIO is in maintenance mode
  but fully functional on current Raspberry Pi OS. If you prefer, the
  driver can be ported to `lgpio` (a drop-in replacement with the same
  pin semantics); the rest of the code is unaffected.
* **Port already in use** — change `PORT` in `app/config.py`, then
  `./scripts/rnk-rpi restart`.

## Security note

The API has **no authentication** — anyone on your network can command
the robot. Keep the Pi on a trusted network, or put it behind a reverse
proxy / firewall if it must be reachable beyond your LAN.
