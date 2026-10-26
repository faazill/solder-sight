"""Machine configuration (YAML -> dataclasses). Unknown keys are rejected to catch typos."""

from dataclasses import dataclass, field, fields, is_dataclass


@dataclass
class SerialCfg:
    port: str = "/dev/ttyUSB0"
    baud: int = 115200
    timeout_s: float = 60.0


@dataclass
class LimitsCfg:
    x_min: float = 0.0
    x_max: float = 200.0
    y_min: float = 0.0
    y_max: float = 200.0
    z_min: float = 0.0
    z_max: float = 60.0


@dataclass
class MotionCfg:
    feed_xy: float = 3000.0
    feed_z: float = 600.0
    z_safe: float = 20.0       # travel height (machine Z)
    z_solder: float = 2.0      # soldering height (machine Z)
    box_origin_x: float = 0.0  # machine X of the reference box's bottom-left corner
    box_origin_y: float = 0.0  # machine Y of the reference box's bottom-left corner
    park_x: float | None = None  # optional: move tip here before taking photos
    park_y: float | None = None
    settle_s: float = 0.4


@dataclass
class SolderCfg:
    on_cmd: str = "M3 S1000"   # command that starts solder feed / heater pulse
    off_cmd: str = "M5"
    dwell_s: float = 1.5
    sync_cmd: str = "G4 P0"    # wait for moves to finish (Marlin: M400)
    home_cmd: str | None = None  # e.g. "$H" (GRBL) or "G28" (Marlin)


@dataclass
class InspectionCfg:
    camera_index: int = 0
    crop_mm: float = 4.0
    max_retries: int = 2
    min_change: float = 2.0       # mean grey change that counts as "something happened"
    bright_v: int = 190           # HSV value threshold for shiny solder
    max_sat: int = 90             # HSV saturation ceiling for shiny solder
    solder_ratio_min: float = 0.08  # below -> RETRY (too little)
    solder_ratio_max: float = 0.45  # above -> HUMAN (excess / bridge)


@dataclass
class Config:
    serial: SerialCfg = field(default_factory=SerialCfg)
    limits: LimitsCfg = field(default_factory=LimitsCfg)
    motion: MotionCfg = field(default_factory=MotionCfg)
    solder: SolderCfg = field(default_factory=SolderCfg)
    inspection: InspectionCfg = field(default_factory=InspectionCfg)


def _from_dict(cls, data):
    names = {f.name for f in fields(cls)}
    unknown = set(data) - names
    if unknown:
        raise ValueError(f"Unknown config keys for {cls.__name__}: {sorted(unknown)}")
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        if is_dataclass(f.type) and isinstance(value, dict):
            value = _from_dict(f.type, value)
        kwargs[f.name] = value
    return cls(**kwargs)


def load_config(path) -> Config:
    import yaml

    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    cfg = _from_dict(Config, data)
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    m, lim = cfg.motion, cfg.limits
    if not (lim.z_min <= m.z_solder < m.z_safe <= lim.z_max):
        raise ValueError("Need z_min <= z_solder < z_safe <= z_max.")
    if (m.park_x is None) != (m.park_y is None):
        raise ValueError("Set both park_x and park_y, or neither.")
    if cfg.inspection.max_retries < 0:
        raise ValueError("max_retries must be >= 0.")
