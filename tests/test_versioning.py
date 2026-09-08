import logging
import unittest

import version_guard
from version import COMPATIBLE_STATE_VERSIONS, VERSION


class DummyTracker:
    def __init__(self):
        self.VERSION = "8.8.1"
        self.COMPATIBLE_STATE_VERSIONS = {"8.8.1"}
        self.LOGGER = logging.getLogger("version-guard-test")
        self.LOGGER.filters.clear()
        self._VERSION_GUARD_INSTALLED = False


class VersioningTests(unittest.TestCase):
    def test_install_uses_public_version_and_all_compatible_states(self):
        tracker = DummyTracker()
        version_guard.install(tracker)

        self.assertEqual(tracker.VERSION, VERSION)
        self.assertTrue(COMPATIBLE_STATE_VERSIONS.issubset(tracker.COMPATIBLE_STATE_VERSIONS))
        self.assertIn(VERSION, tracker.COMPATIBLE_STATE_VERSIONS)

    def test_runtime_filter_rewrites_only_log_labels(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="V8.8.1 | execução operacional",
            args=(),
            exc_info=None,
        )
        version_guard.RuntimeVersionFilter().filter(record)
        self.assertIn(f"V{VERSION}", record.msg)
        self.assertNotIn("V8.8.1", record.msg)


if __name__ == "__main__":
    unittest.main()
