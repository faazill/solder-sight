"""G-code machine driver (GRBL / Marlin style 'ok' protocol) with a dry-run transport."""

from __future__ import annotations

import time
from typing import Protocol

from config import Config


class MachineError(Exception):
    pass


class LimitError(MachineError):
    pass


class Transport(Protocol):
    def send(self, line: str) -> None: ...
    def close(self) -> None: ...


class DryRunTransport:
    """Records G-code instead of sending it. Nothing moves, nothing heats."""

    def __init__(self):
        self.lines: list[str] = []

    def send(self, line: str) -> None:
        self.lines.append(line)

    def close(self) -> None:
        pass


class SerialTransport:
    def __init__(self, port: str, baud: int, timeout_s: float):
        import serial

        self.timeout_s = timeout_s
        self.ser = serial.Serial(port, baud, timeout=0.5)
        time.sleep(2.0)  # many boards reset when the port opens
        self.ser.reset_input_buffer()

    def send(self, line: str) -> None:
        self.ser.write((line.strip() + "\n").encode())
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            resp = self.ser.readline().decode(errors="ignore").strip().lower()
            if not resp or resp.startswith("<"):  # blank or GRBL status report
                continue
            if resp.startswith("ok"):
                return
            if "error" in resp or "alarm" in resp:
                raise MachineError(f"Machine replied '{resp}' to '{line}'")
        raise MachineError(f"Timed out waiting for 'ok' after '{line}'")

    def close(self) -> None:
        self.ser.close()


class Machine:
    def __init__(self, cfg: Config, transport: Transport, sleep=time.sleep):
        self.cfg = cfg
        self.transport = transport
        self.sleep = sleep

    def send(self, line: str) -> None:
        self.transport.send(line)

    def prepare(self) -> None:
        self.send("G21")  # millimetres
        self.send("G90")  # absolute

    def home(self) -> None:
        if self.cfg.solder.home_cmd:
            self.send(self.cfg.solder.home_cmd)

    @staticmethod
    def _check(name, value, lo, hi):
        if not lo <= value <= hi:
            raise LimitError(f"{name}={value:.3f} is outside the limit [{lo}, {hi}]")

    def move_xy(self, x: float, y: float) -> None:
        lim, m = self.cfg.limits, self.cfg.motion
        self._check("X", x, lim.x_min, lim.x_max)
        self._check("Y", y, lim.y_min, lim.y_max)
        self.send(f"G1 X{x:.3f} Y{y:.3f} F{m.feed_xy:g}")

    def move_xy_box(self, x_mm: float, y_mm: float) -> None:
        m = self.cfg.motion
        self.move_xy(m.box_origin_x + x_mm, m.box_origin_y + y_mm)

    def move_z(self, z: float) -> None:
        lim = self.cfg.limits
        self._check("Z", z, lim.z_min, lim.z_max)
        self.send(f"G1 Z{z:.3f} F{self.cfg.motion.feed_z:g}")

    def pulse(self) -> None:
        s = self.cfg.solder
        self.send(s.sync_cmd)
        self.send(s.on_cmd)
        try:
            self.sleep(s.dwell_s)
        finally:
            self.send(s.off_cmd)  # always switched off, even on error

    def safe_stop(self) -> None:
        """Best effort: solder off, tip up. Never raises."""
        for action in (lambda: self.send(self.cfg.solder.off_cmd),
                       lambda: self.move_z(self.cfg.motion.z_safe)):
            try:
                action()
            except Exception:
                pass
