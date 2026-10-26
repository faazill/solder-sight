import pytest

from config import load_config


def test_example_config_loads():
    cfg = load_config("machine.example.yaml")
    assert cfg.motion.z_solder < cfg.motion.z_safe


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("motion:\n  z_safee: 10\n")
    with pytest.raises(ValueError):
        load_config(p)


def test_z_order_validated(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("motion:\n  z_safe: 5\n  z_solder: 8\n")
    with pytest.raises(ValueError):
        load_config(p)
