"""Authentication tests use fake tokens and never access credential storage."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.canvas_ops import get_canvas_client


class CanvasAuthTests(unittest.TestCase):
    def connect(self, env_token=None, stored_token=None, explicit_token=None, error=None):
        env = {"CANVAS_API_URL": "https://canvas.example.test"}
        if env_token is not None:
            env["CANVAS_TOKEN"] = env_token
        lookup = Mock(return_value=stored_token, side_effect=error)
        with patch.dict(os.environ, env, clear=True), patch.dict(
            "sys.modules", {"keyring": SimpleNamespace(get_password=lookup)}
        ), patch("src.canvas_ops.Canvas") as canvas:
            get_canvas_client(api_token=explicit_token)
        return lookup, canvas

    def test_env_takes_priority_without_accessing_keyring(self):
        lookup, canvas = self.connect(env_token="fake-env", stored_token="fake-stored")
        lookup.assert_not_called()
        canvas.assert_called_once_with("https://canvas.example.test", "fake-env")

    def test_fallback_to_keyring(self):
        for token in (None, "", "  "):
            with self.subTest(token=token):
                lookup, canvas = self.connect(env_token=token, stored_token="fake-stored")
                lookup.assert_called_once_with("canvas-autograder", "CANVAS_TOKEN")
                canvas.assert_called_once_with("https://canvas.example.test", "fake-stored")

    def test_explicit_argument_still_supported(self):
        lookup, canvas = self.connect(env_token="fake-env", explicit_token="fake-explicit")
        lookup.assert_not_called()
        canvas.assert_called_once_with("https://canvas.example.test", "fake-explicit")

    def test_missing_token_is_clear(self):
        with self.assertRaisesRegex(ValueError, "Missing Canvas token"):
            self.connect()

    def test_backend_error_does_not_expose_details(self):
        with self.assertRaisesRegex(ValueError, "Cannot access credential storage") as ctx:
            self.connect(error=RuntimeError("private backend details"))
        self.assertNotIn("private backend details", str(ctx.exception))
