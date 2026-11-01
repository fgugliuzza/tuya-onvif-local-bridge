# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib
import tomllib
from pathlib import Path


def test_import_package():
    for module in ('app', 'config', 'discovery', 'onvif', 'presets', 'soap', 'tuya'):
        importlib.import_module('tuya_onvif_local_bridge.' + module)

def test_distribution_and_entrypoint():
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    assert project["name"] == "tuya-onvif-local-bridge"
    assert project["version"] == "0.1.18"
    assert project["scripts"]["tuya-onvif-local-bridge"] == "tuya_onvif_local_bridge.app:main"

def test_preset_identity_seed_unchanged():
    import inspect
    from tuya_onvif_local_bridge.config import Config
    assert "'tuya-onvif:' + os.environ['TUYA_DEVICE_ID']" in inspect.getsource(Config.from_env)
