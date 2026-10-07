import unittest
from pathlib import Path

import tempfile
from unittest import mock

from tools import tv_launch
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



class WatchTest(unittest.TestCase):
    SCREEN = (-1920, 0, 0, 1080, False)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(tv_launch, "OFF_FLAG", Path(tmp.name) / "apagada")
        patcher.start()
        self.addCleanup(patcher.stop)
        log = mock.patch.object(tv_launch, "log")
        log.start()
        self.addCleanup(log.stop)
        self.opened, self.killed = [], []

    def run_cmd(self, pids):
        def run(cmd, **kwargs):
            if cmd[0] == "taskkill":
                self.killed.append(cmd[2])
            return mock.Mock(stdout=" ".join(map(str, pids)))
        return run

    def test_open_tv_is_left_alone(self):
        out = tv_launch.watch(self.SCREEN, windows=lambda: [1], open_tv=lambda: self.opened.append(1), run=self.run_cmd([]))
        self.assertEqual((out, self.opened), ("abierta", []))

    def test_closed_tv_is_reopened(self):
        out = tv_launch.watch(self.SCREEN, windows=lambda: [], open_tv=lambda: self.opened.append(1), run=self.run_cmd([]))
        self.assertEqual((out, self.opened, self.killed), ("reabierta", [1], []))

    def test_error_page_restarts_only_the_tv_browser(self):
        tv_launch.watch(self.SCREEN, windows=lambda: [], open_tv=lambda: self.opened.append(1), run=self.run_cmd([4242]))
        self.assertEqual((self.killed, self.opened), (["4242"], [1]))

    def test_switched_off_or_no_tv_screen_does_nothing(self):
        tv_launch.OFF_FLAG.write_text("x", encoding="utf-8")
        self.assertEqual(tv_launch.watch(self.SCREEN, windows=lambda: [], open_tv=lambda: self.opened.append(1)), "nada")
        tv_launch.OFF_FLAG.unlink()
        self.assertEqual(tv_launch.watch(None, windows=lambda: [], open_tv=lambda: self.opened.append(1)), "nada")
        self.assertEqual(self.opened, [])


if __name__ == "__main__":
    unittest.main()
