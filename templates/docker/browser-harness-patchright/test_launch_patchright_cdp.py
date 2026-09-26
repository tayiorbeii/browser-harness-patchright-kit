import importlib.util
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


sys.modules.setdefault("patchright", types.ModuleType("patchright"))
sync_api = types.ModuleType("patchright.sync_api")
sync_api.sync_playwright = object()
sys.modules.setdefault("patchright.sync_api", sync_api)

MODULE_PATH = Path(__file__).with_name("launch_patchright_cdp.py")
SPEC = importlib.util.spec_from_file_location("launch_patchright_cdp", MODULE_PATH)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class LauncherRecoveryTests(unittest.TestCase):
    def test_websocket_frame_is_masked_and_round_trips(self) -> None:
        payload = b'{"id":1}'

        frame = launcher.websocket_frame(payload)

        self.assertEqual(frame[0], 0x81)
        self.assertEqual(frame[1] & 0x80, 0x80)
        self.assertEqual(frame[1] & 0x7F, len(payload))
        mask = frame[2:6]
        decoded = bytes(byte ^ mask[index % 4] for index, byte in enumerate(frame[6:]))
        self.assertEqual(decoded, payload)

    def test_healthy_browser_resets_consecutive_failure_budget(self) -> None:
        with patch.object(launcher, "BROWSER_RELAUNCH_GRACE_S", 60.0):
            self.assertEqual(launcher.next_failure_count(4, 60.0), 0)
            self.assertEqual(launcher.next_failure_count(4, 59.999), 5)
            self.assertEqual(launcher.next_failure_count(0, None), 1)

    def test_wait_status_reports_exit_or_signal(self) -> None:
        self.assertEqual(launcher.decode_wait_status(7 << 8), (7, None))
        self.assertEqual(launcher.decode_wait_status(9), (None, 9))

    def test_stale_display_lock_and_socket_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp, tempfile.TemporaryDirectory() as raw_proc:
            tmp_root = Path(raw_tmp)
            lock = tmp_root / ".X99-lock"
            socket_dir = tmp_root / ".X11-unix"
            display_socket = socket_dir / "X99"
            socket_dir.mkdir()
            lock.write_text("123\n")
            server = socket.socket(socket.AF_UNIX)
            server.bind(str(display_socket))
            server.close()

            removed = launcher.clear_stale_display_artifacts(":99", Path(raw_proc), tmp_root)

            self.assertEqual(removed, [lock, display_socket])
            self.assertFalse(lock.exists())
            self.assertFalse(display_socket.exists())

    def test_live_display_process_preserves_lock_and_socket(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp, tempfile.TemporaryDirectory() as raw_proc:
            tmp_root = Path(raw_tmp)
            proc_root = Path(raw_proc)
            lock = tmp_root / ".X99-lock"
            socket_dir = tmp_root / ".X11-unix"
            display_socket = socket_dir / "X99"
            socket_dir.mkdir()
            lock.write_text("123\n")
            server = socket.socket(socket.AF_UNIX)
            server.bind(str(display_socket))
            server.close()
            process = proc_root / "123"
            process.mkdir()
            (process / "cmdline").write_bytes(b"/usr/bin/Xtigervnc\0:99\0")

            removed = launcher.clear_stale_display_artifacts(":99", proc_root, tmp_root)

            self.assertEqual(removed, [])
            self.assertTrue(lock.exists())
            self.assertTrue(display_socket.exists())

    def test_find_browser_pid_ignores_renderer_processes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_proc:
            proc_root = Path(raw_proc)
            for pid, args in {
                "10": b"/usr/bin/chromium\0--user-data-dir=/data/profile\0--type=renderer\0",
                "11": b"/usr/bin/chromium\0--user-data-dir=/data/profile\0",
            }.items():
                process = proc_root / pid
                process.mkdir()
                (process / "cmdline").write_bytes(args)

            self.assertEqual(launcher.find_browser_pid(Path("/data/profile"), proc_root), 11)


if __name__ == "__main__":
    unittest.main()
