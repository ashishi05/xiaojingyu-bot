"""Regression checks with a fake screen; never send native mouse/keyboard input."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location(
    "desktop_regression",
    Path(__file__).resolve().parents[1] / "AstrBot/data/plugins/local_desktop/desktop.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class DesktopRegression(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.backend = Mock()
        self.backend.bounds.return_value = (-1920, 0, 3840, 1080)
        self.backend.capture.return_value = ("fake.png", (1920, 540))
        self.controller = m.DesktopController(self.backend, clock=lambda: self.now)
        self.frame = self.controller.screenshot("owner")

    def act(self, **kwargs):
        return self.controller.act("owner", capture_id=self.frame["capture_id"], **kwargs)

    def test_click_maps_coordinates_and_consumes_screenshot(self):
        self.act(action="click", x=1000, y=20)
        self.assertEqual(self.backend.perform.call_args.args[0]["x"], 80)
        self.assertEqual(self.backend.perform.call_args.args[0]["y"], 40)
        with self.assertRaises(ValueError):
            self.act(action="click", x=1, y=1)
        self.backend.perform.assert_called_once()

    def test_invalid_coordinates_keys_and_text_do_not_execute(self):
        for args in [{"action": "click", "x": -1}, {"action": "click", "x": 1920}, {"action": "keys", "keys": "A+B"}, {"action": "text", "text": "hello\n"}, {"action": "scroll", "amount": 0}]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.act(**args)
        self.backend.perform.assert_not_called()

    def test_expired_or_changed_screen_does_not_execute(self):
        self.now += 121
        with self.assertRaises(ValueError):
            self.act(action="click")
        self.now = 1000
        self.backend.bounds.return_value = (0, 0, 1920, 1080)
        with self.assertRaises(ValueError):
            self.act(action="click")
        self.backend.perform.assert_not_called()

    def test_confirmation_is_owner_bound_and_single_use(self):
        pending = self.act(action="click", risk="send", reason="发送测试")
        token = pending["confirmation"]
        self.backend.perform.assert_not_called()
        with self.assertRaises(ValueError):
            self.controller.confirm("other", token)
        self.controller.confirm("owner", token)
        with self.assertRaises(ValueError):
            self.controller.confirm("owner", token)
        self.backend.perform.assert_called_once()

    def test_confirmation_expiry_and_stop_clear_pending_actions(self):
        pending = self.act(action="click", risk="delete", reason="删除测试")
        self.now += 61
        with self.assertRaises(ValueError):
            self.controller.confirm("owner", pending["confirmation"])
        self.controller.stop()
        with self.assertRaises(ValueError):
            self.act(action="click")
        self.controller.resume()
        with self.assertRaises(ValueError):
            self.act(action="click")
        self.backend.perform.assert_not_called()

    def test_supported_input_shapes_reach_backend(self):
        for args in [{"action": "drag", "x": 1, "y": 2, "end_x": 3, "end_y": 4}, {"action": "scroll", "amount": -3}, {"action": "text", "text": "中文测试"}, {"action": "keys", "keys": "CTRL+A"}]:
            with self.subTest(args=args):
                self.frame = self.controller.screenshot("owner")
                self.assertEqual(self.act(**args)["status"], "done")
        self.assertEqual(self.backend.perform.call_count, 4)


if __name__ == "__main__":
    unittest.main()
