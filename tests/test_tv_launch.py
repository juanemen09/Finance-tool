import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

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
        self.assertIn("--disable-background-mode", args)
        self.assertIn("--disable-extensions", args)
        self.assertIn("--app=http://127.0.0.1:8765/tv", args)
        self.assertIn("--user-data-dir=perfil", args)
        x, y = map(int, next(a for a in args if a.startswith("--window-position=")).split("=")[1].split(","))
        self.assertTrue(TV[0] < x < TV[2] and TV[1] <= y < TV[3], "la ventana nace dentro de la TV")



class LifecycleTest(unittest.TestCase):
    def test_watchdog_option_no_longer_exists(self):
        """Cerrar la TV debe ser final: no puede quedar una ruta CLI que la reabra."""
        with mock.patch.object(tv_launch, "monitors", return_value=[]):
            with redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    tv_launch.main(["--vigilar"])

    def test_panel_owned_by_launcher_stops_when_tv_closes(self):
        panel, browser = mock.Mock(), mock.Mock()
        panel.poll.return_value = None
        with mock.patch.object(tv_launch, "panel_up", side_effect=[False, True]), \
             mock.patch.object(tv_launch, "start_panel", return_value=panel), \
             mock.patch.object(tv_launch, "CHROME_CANDIDATES", (Path(tv_launch.sys.executable),)), \
             mock.patch.object(tv_launch.subprocess, "Popen", return_value=browser), \
             mock.patch.object(tv_launch.time, "sleep"), \
             mock.patch.object(tv_launch, "log"):
            self.assertEqual(tv_launch.launch(TV), 0)
        browser.wait.assert_called_once_with()
        panel.terminate.assert_called_once_with()
        panel.wait.assert_called_once_with(timeout=5)

    def test_owned_panel_stops_if_browser_is_missing(self):
        panel = mock.Mock()
        panel.poll.return_value = None
        with mock.patch.object(tv_launch, "panel_up", side_effect=[False, True]), \
             mock.patch.object(tv_launch, "start_panel", return_value=panel), \
             mock.patch.object(tv_launch, "CHROME_CANDIDATES", ()), \
             mock.patch.object(tv_launch.time, "sleep"), \
             mock.patch.object(tv_launch, "log"):
            self.assertEqual(tv_launch.launch(TV), 1)
        panel.terminate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
