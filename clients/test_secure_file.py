import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path


CLIENT_DIR = Path(__file__).resolve().parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from secure_file import (  # noqa: E402
    SecureFileError,
    _SecureOpenHooks,
    secure_read_bounded_regular_file,
)


class SecureFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_bounded_regular_empty_and_exact_limit(self):
        path = self.root / "document"
        path.write_bytes(b"trusted")
        self.assertEqual(
            secure_read_bounded_regular_file(str(path), 7),
            b"trusted",
        )
        empty = self.root / "empty"
        empty.write_bytes(b"")
        self.assertEqual(
            secure_read_bounded_regular_file(str(empty), 0),
            b"",
        )
        path.write_bytes(b"trusted!")
        with self.assertRaises(SecureFileError):
            secure_read_bounded_regular_file(str(path), 7)

    def test_path_components_and_special_objects_fail_closed(self):
        target = self.root / "target"
        target.write_bytes(b"trusted")
        final_link = self.root / "final-link"
        final_link.symlink_to(target)
        dangling = self.root / "dangling"
        dangling.symlink_to(self.root / "missing")
        directory = self.root / "directory"
        directory.mkdir()
        fifo = self.root / "fifo"
        os.mkfifo(fifo, 0o600)
        socket_path = self.root / "socket"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        socket_available = True
        try:
            listener.bind(str(socket_path))
        except PermissionError:
            socket_available = False
            listener.close()
        else:
            self.addCleanup(listener.close)
        real_parent = self.root / "real"
        real_parent.mkdir()
        nested = real_parent / "nested"
        nested.write_bytes(b"trusted")
        linked_parent = self.root / "linked"
        linked_parent.symlink_to(real_parent, target_is_directory=True)

        paths = {
            "empty": "",
            "relative": "relative",
            "root": "/",
            "traversal": str(self.root / "real") + "/../target",
            "repeated": str(self.root) + "//target",
            "nul": str(target) + "\x00suffix",
            "final-link": str(final_link),
            "dangling": str(dangling),
            "directory": str(directory),
            "fifo": str(fifo),
            "character-device": "/dev/null",
            "intermediate-link": str(linked_parent / "nested"),
        }
        if socket_available:
            paths["socket"] = str(socket_path)
        for name, path in paths.items():
            with self.subTest(name=name), self.assertRaises(SecureFileError) as captured:
                secure_read_bounded_regular_file(path, 4096)
            if path:
                self.assertNotIn(path, str(captured.exception))

    def test_parent_replacement_cannot_redirect_open(self):
        parent = self.root / "managed"
        parent.mkdir()
        moved = self.root / "managed-held"
        attacker = self.root / "attacker"
        attacker.mkdir()
        path = parent / "config.json"
        path.write_bytes(b"trusted")
        (attacker / "config.json").write_bytes(b"attacker")

        def replace_parent(_descriptor):
            parent.rename(moved)
            parent.symlink_to(attacker, target_is_directory=True)

        data = secure_read_bounded_regular_file(
            str(path),
            4096,
            _test_hooks=_SecureOpenHooks(before_file_open=replace_parent),
        )
        self.assertEqual(data, b"trusted")
        self.assertNotIn(b"attacker", data)

    def test_intermediate_replacement_cannot_redirect_traversal(self):
        trusted = self.root / "trusted"
        nested = trusted / "nested"
        nested.mkdir(parents=True)
        moved = self.root / "trusted-held"
        attacker = self.root / "attacker"
        (attacker / "nested").mkdir(parents=True)
        path = nested / "config.json"
        path.write_bytes(b"trusted")
        (attacker / "nested" / "config.json").write_bytes(b"attacker")
        replaced = False

        def replace_intermediate(_depth, component, _descriptor):
            nonlocal replaced
            if component != "trusted" or replaced:
                return
            replaced = True
            trusted.rename(moved)
            trusted.symlink_to(attacker, target_is_directory=True)

        data = secure_read_bounded_regular_file(
            str(path),
            4096,
            _test_hooks=_SecureOpenHooks(
                after_directory_open=replace_intermediate,
            ),
        )
        self.assertEqual(data, b"trusted")

    def test_opened_descriptor_survives_unlink_and_loops_do_not_leak(self):
        path = self.root / "document"
        path.write_bytes(b"trusted")

        def unlink_opened(_descriptor):
            path.unlink()

        self.assertEqual(
            secure_read_bounded_regular_file(
                str(path),
                4096,
                _test_hooks=_SecureOpenHooks(
                    after_file_open=unlink_opened,
                ),
            ),
            b"trusted",
        )

        if not Path("/proc/self/fd").is_dir():
            self.skipTest("descriptor accounting requires Linux /proc")
        path.write_bytes(b"trusted")
        oversized = self.root / "oversized"
        oversized.write_bytes(b"x" * 4097)
        directory = self.root / "directory"
        directory.mkdir()
        before = len(list(Path("/proc/self/fd").iterdir()))
        for index in range(1000):
            self.assertEqual(
                secure_read_bounded_regular_file(str(path), 4096),
                b"trusted",
            )
            with self.assertRaises(SecureFileError):
                secure_read_bounded_regular_file(
                    str(self.root / ("missing-%d" % index)),
                    4096,
                )
            with self.assertRaises(SecureFileError):
                secure_read_bounded_regular_file(str(oversized), 4096)
            with self.assertRaises(SecureFileError):
                secure_read_bounded_regular_file(str(directory), 4096)
        after = len(list(Path("/proc/self/fd").iterdir()))
        self.assertLessEqual(after, before + 4)


if __name__ == "__main__":
    unittest.main()
