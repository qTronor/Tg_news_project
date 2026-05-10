from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "rbc_telegram_collector"))

from collector.config import AppConfig
from collector.sources.telegram import (
    TelegramProxySettings,
    _build_telethon_proxy,
    _load_proxy_settings,
)


class TelegramProxyConfigUnitTest(unittest.TestCase):
    def test_app_config_accepts_proxy_block(self) -> None:
        cfg = AppConfig.model_validate(
            {
                "channels": [{"name": "rbc_news"}],
                "telegram": {
                    "proxy": {
                        "enabled": True,
                        "scheme": "socks5",
                        "host": "127.0.0.1",
                        "port": 1080,
                        "username": "user",
                        "password": "pass",
                        "rdns": False,
                    }
                },
            }
        )

        self.assertTrue(cfg.telegram.proxy.enabled)
        self.assertEqual(cfg.telegram.proxy.host, "127.0.0.1")
        self.assertEqual(cfg.telegram.proxy.port, 1080)
        self.assertFalse(cfg.telegram.proxy.rdns)

    def test_proxy_settings_load_from_env(self) -> None:
        env = {
            "TG_PROXY_ENABLED": "true",
            "TG_PROXY_SCHEME": "http",
            "TG_PROXY_HOST": "proxy.internal",
            "TG_PROXY_PORT": "8080",
            "TG_PROXY_USERNAME": "alice",
            "TG_PROXY_PASSWORD": "secret",
            "TG_PROXY_RDNS": "false",
        }
        with patch.dict("os.environ", env, clear=False):
            settings = _load_proxy_settings(None)

        self.assertEqual(
            settings,
            TelegramProxySettings(
                enabled=True,
                scheme="http",
                host="proxy.internal",
                port=8080,
                username="alice",
                password="secret",
                rdns=False,
            ),
        )

    def test_build_telethon_proxy_uses_pysocks_constants(self) -> None:
        settings = TelegramProxySettings(
            enabled=True,
            scheme="socks5",
            host="proxy.internal",
            port=1080,
            username="alice",
            password="secret",
            rdns=True,
        )
        proxy = _build_telethon_proxy(settings)

        self.assertEqual(
            proxy,
            (
                "socks5",
                "proxy.internal",
                1080,
                True,
                "alice",
                "secret",
            ),
        )
