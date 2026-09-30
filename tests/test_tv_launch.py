import unittest
from pathlib import Path

from tools.tv_launch import chrome_args, pick_screen

MAIN = (0, 0, 1920, 1080, True)
TV = (1920, 0, 5760, 2160, False)


class ScreenTest(unittest.TestCase):
    def test_prefers_the_secondary_screen(self):
        self.assertEqual(pick_screen([MAIN, TV]), TV)

    def test_never_covers_the_work_monitor_unless_asked(self):
        self.assertIsNone(pick_screen([MAIN]))
        self.assertEqual(pick_screen([MAIN], allow_primary=True), MAIN)

    def test_largest_secondary_wins(self):
        small = (-1280, 0, 0, 1024, False)
        self.assertEqual(pick_screen([small, MAIN, TV]), TV)


class ChromeArgsTest(unittest.TestCase):
    def test_kiosk_inside_the_tv_with_own_profile(self):
        args = chrome_args(Path("chrome.exe"), "http://127.0.0.1:8765/tv", TV, Path("perfil"))
        self.assertIn("--kiosk", args)
        self.assertIn("--app=http://127.0.0.1:8765/tv", args)
        self.assertIn("--user-data-dir=perfil", args)
        x, y = map(int, next(a for a in args if a.startswith("--window-position=")).split("=")[1].split(","))
        self.assertTrue(TV[0] < x < TV[2] and TV[1] <= y < TV[3], "la ventana nace dentro de la TV")


if __name__ == "__main__":
    unittest.main()
