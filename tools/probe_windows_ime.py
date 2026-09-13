"""Read-only by default; --self-test only changes its own empty input window.

The self-test never sends keystrokes or changes keyboard layout/profile. It
restores the input context's original open/conversion bits before closing.
No window titles, process names or input text are collected.
"""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from windows_ime import (  # noqa: E402
    IMC_SETCONVERSIONMODE, IMC_SETOPENSTATUS, NativeImeBackend,
)


def summary(state):
    return {'has_focus': bool(state.focus), 'layout': hex(state.layout),
            'has_ime_window': bool(state.ime_window), 'is_pinyin': state.is_pinyin,
            'chinese': state.chinese, 'open_status': state.open_status,
            'conversion': state.conversion, 'reason': state.reason}


def self_test():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QLineEdit

    app = QApplication([])
    window = QLineEdit()
    window.setWindowTitle('微软拼音同步：隔离验证')
    window.setPlaceholderText('仅验证此空白测试窗口的输入法状态')
    window.resize(500, 80)
    window.show()
    window.activateWindow()
    window.setFocus()
    # Windows may decline this ordinary foreground request from a background
    # agent. In that case the test reports unavailable and performs no writes.
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow(int(window.winId()))
    report = {'passed': False, 'steps': [], 'restored': False}

    def run():
        backend = NativeImeBackend()
        initial = None
        try:
            initial = backend.snapshot()
            report['initial'] = summary(initial)
            if initial.process_id != os.getpid() or not initial.focus:
                report['reason'] = 'test_window_not_foreground'
                return
            if initial.is_pinyin is not True or initial.chinese is None:
                report['reason'] = initial.reason or 'test_window_ime_unavailable'
                return
            for requested in (True, False, True, False):
                before = backend.snapshot()
                if before.target_key != initial.target_key:
                    report['reason'] = 'foreground_changed'
                    return
                result = backend.set_chinese(before, requested)
                report['steps'].append({'requested': requested, 'ok': result.ok,
                                        'reason': result.reason, 'state': summary(result.state)})
                if not result.ok:
                    report['reason'] = result.reason
                    return
            report['passed'] = True
        except Exception as exc:
            report['reason'] = type(exc).__name__ + ': ' + str(exc)
        finally:
            try:
                # Restoring is also target-bound. Never restore into an
                # unrelated window if the user changed foreground meanwhile.
                if (initial and initial.process_id == os.getpid()
                        and initial.chinese is not None and backend.target_matches(initial)):
                    backend._set(initial, IMC_SETCONVERSIONMODE, initial.conversion)
                    backend._set(initial, IMC_SETOPENSTATUS, int(initial.open_status))
                    final = backend.snapshot()
                    report['restored'] = (final.target_key == initial.target_key
                                          and final.conversion == initial.conversion
                                          and final.open_status == initial.open_status)
                    report['final'] = summary(final)
            finally:
                backend.close()
                window.close()
                app.quit()

    QTimer.singleShot(800, run)
    QTimer.singleShot(15000, app.quit)
    app.exec_()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] and report['restored'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    backend = NativeImeBackend()
    try:
        print(json.dumps(summary(backend.snapshot()), ensure_ascii=False, indent=2))
    finally:
        backend.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
