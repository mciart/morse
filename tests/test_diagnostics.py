"""Exercise log installation in separate processes, without a GUI or hooks."""

from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class DiagnosticsTests(unittest.TestCase):
    def test_process_logs_keep_previous_run_and_capture_unhandled_exception(self):
        project = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            script = (
                'import logging, sys; '
                'from crash_diagnostics import install_diagnostics; '
                'install_diagnostics(sys.argv[1]); '
                'logging.info("diagnostic-check"); '
                'raise RuntimeError("diagnostic-test-error")'
            )
            for _ in range(2):
                process = subprocess.run([sys.executable, '-B', '-c', script, directory],
                                         cwd=project, capture_output=True, timeout=15)
                self.assertEqual(process.returncode, 1, process.stderr)
            logs = list((Path(directory) / 'logs').glob('morsewriter-*.log'))
            self.assertEqual(len(logs), 2)
            for log in logs:
                content = log.read_text(encoding='utf-8')
                self.assertIn('pid=', content)
                self.assertIn('diagnostic-check', content)
                self.assertIn('Unhandled Python exception', content)
                self.assertIn('diagnostic-test-error', content)
            fault_logs = list((Path(directory) / 'logs').glob('crash-*.log'))
            self.assertEqual(len(fault_logs), 2)
            self.assertTrue(all('pid=' in log.read_text(encoding='utf-8') for log in fault_logs))


if __name__ == '__main__':
    unittest.main()
