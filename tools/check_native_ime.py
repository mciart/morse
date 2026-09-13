"""Verify real Microsoft Pinyin composition in an owned child process.

This optional desktop check never targets the user's application. It obtains
ordinary foreground permission for its own empty editor or reports unavailable.
No hooks, settings, keyboard profiles or registry values are changed. A real
nihao composition is required before checking the English transition.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import queue
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from windows_ime import (  # noqa: E402
    IMC_SETCONVERSIONMODE, IMC_SETOPENSTATUS, NativeImeBackend,
)


def child_window():
    from PyQt5.QtCore import QObject, QTimer, pyqtSignal
    from PyQt5.QtWidgets import QApplication, QLineEdit

    class Editor(QLineEdit):
        def __init__(self):
            super().__init__()
            self.preedit = ''
            self.commits = []

        def inputMethodEvent(self, event):
            self.preedit = event.preeditString()
            if event.commitString():
                self.commits.append(event.commitString())
            super().inputMethodEvent(event)

    class Pipe(QObject):
        message = pyqtSignal(str)

    app = QApplication([])
    editor = Editor()
    editor.setWindowTitle('微软拼音候选：独立进程隔离验证')
    editor.setPlaceholderText('仅验证此测试框：nihao → 英文 → nihaoe')
    editor.resize(620, 95)
    editor.show()
    editor.activateWindow()
    editor.setFocus()
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    foreground_granted = bool(user32.SetForegroundWindow(int(editor.winId())))
    pipe = Pipe()

    def command(message):
        if message == 'get':
            print(json.dumps({'text': editor.text(), 'preedit': editor.preedit,
                              'commits': editor.commits,
                              'process_id': os.getpid(), 'window_id': int(editor.winId()),
                              'foreground_request_granted': foreground_granted,
                              'owns_foreground': user32.GetForegroundWindow() == int(editor.winId())},
                             ensure_ascii=False), flush=True)
        elif message == 'close':
            editor.close()
            app.quit()

    pipe.message.connect(command)

    def read_commands():
        for line in sys.stdin:
            pipe.message.emit(line.strip())

    threading.Thread(target=read_commands, daemon=True).start()
    QTimer.singleShot(25000, app.quit)
    app.exec_()


class _KeyboardInput(ctypes.Structure):
    _fields_ = [('vk', wintypes.WORD), ('scan', wintypes.WORD),
                ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('extra', ctypes.c_size_t)]


class _MouseInput(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                ('data', wintypes.DWORD), ('flags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]


class _InputUnion(ctypes.Union):
    _fields_ = [('keyboard', _KeyboardInput), ('mouse', _MouseInput)]


class _Input(ctypes.Structure):
    _anonymous_ = ('value',)
    _fields_ = [('type', wintypes.DWORD), ('value', _InputUnion)]


def check():
    report = {'status': 'unavailable', 'restored': None, 'samples': []}
    if platform.system() != 'Windows':
        return dict(report, reason='windows_required')
    environment = dict(os.environ, PYTHONIOENCODING='utf-8')
    process = subprocess.Popen(
        [sys.executable, '-u', str(Path(__file__).resolve()), '--child'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW)
    responses = queue.Queue()

    def read_responses():
        for line in process.stdout:
            responses.put(line)

    threading.Thread(target=read_responses, daemon=True).start()
    backend = NativeImeBackend()
    initial = None
    editor_process_id = None
    editor_window_id = None
    changed = False
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    # Delegate only permission this test launcher already has to its own child.
    # Windows still decides whether either process can acquire foreground.
    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.AllowSetForegroundWindow.restype = wintypes.BOOL
    user32.AllowSetForegroundWindow(process.pid)

    def editor_state():
        process.stdin.write('get\n')
        process.stdin.flush()
        return json.loads(responses.get(timeout=5))

    def owns_target():
        return (initial is not None and initial.process_id == editor_process_id
                and initial.foreground == editor_window_id
                and backend.target_matches(initial))

    def press(vk):
        if not owns_target():
            raise RuntimeError('test_window_lost_foreground')
        events = (_Input * 2)(
            _Input(type=1, keyboard=_KeyboardInput(vk=vk)),
            _Input(type=1, keyboard=_KeyboardInput(vk=vk, flags=2)))
        if user32.SendInput(2, events, ctypes.sizeof(_Input)) != 2:
            raise RuntimeError('test_key_input_failed')

    try:
        # Wait for the child UI, not a guessed Python/Qt startup duration.
        report['initial_editor'] = editor_state()
        # On Windows a venv python.exe can be a redirector whose Popen.pid is
        # not the GUI interpreter PID. This private pipe belongs to our child;
        # bind to its reported real PID AND exact native window handle.
        editor_process_id = report['initial_editor'].pop('process_id')
        editor_window_id = report['initial_editor'].pop('window_id')
        time.sleep(.2)
        initial = backend.snapshot()
        captured = backend.capture_target()
        report['target_diagnostic'] = {
            'snapshot_owned': initial.process_id == editor_process_id,
            'captured_owned': captured.process_id == editor_process_id,
            'foreground_owned': captured.foreground == editor_window_id,
            'same_target': captured.target_key == initial.target_key,
            'snapshot_reason': initial.reason, 'captured_reason': captured.reason,
        }
        if not owns_target():
            report['reason'] = 'test_window_not_foreground'
            return report
        if initial.is_pinyin is not True or initial.chinese is None:
            report['reason'] = initial.reason or 'microsoft_pinyin_unavailable'
            return report
        report['status'] = 'failed'
        changed = True
        result = backend.set_chinese(initial, True)
        if not result.ok:
            raise RuntimeError('enable_chinese_failed: ' + result.reason)
        for letter in 'NIHAO':
            press(ord(letter))
            time.sleep(.05)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not owns_target():
                raise RuntimeError('test_window_lost_foreground')
            before = editor_state()
            if before['preedit'].replace("'", '') == 'nihao' and not before['text']:
                break
            time.sleep(.1)
        else:
            raise RuntimeError('real_nihao_composition_not_observed')
        report['composition_before'] = before
        result = backend.set_chinese(initial, False)
        report['english_request'] = {'ok': result.ok, 'reason': result.reason}
        if not result.ok:
            raise RuntimeError('switch_to_english_failed: ' + result.reason)
        began = time.monotonic()
        for at in (.15, .3, 1.0):
            time.sleep(max(0, began + at - time.monotonic()))
            state, editor = backend.snapshot(), editor_state()
            sample = {'at_seconds': at, 'chinese': state.chinese,
                      'conversion': state.conversion, 'open_status': state.open_status,
                      'same_target': state.target_key == initial.target_key,
                      'text': editor['text'], 'preedit': editor['preedit']}
            report['samples'].append(sample)
            if not (sample['same_target'] and state.is_pinyin is True
                    and state.chinese is False and editor['text'] == 'nihao'
                    and editor['preedit'] == ''):
                raise RuntimeError('composition_not_preserved_in_english')
        press(ord('E'))
        time.sleep(.3)
        report['after_english_e'] = editor_state()
        if report['after_english_e']['text'] != 'nihaoe' or report['after_english_e']['preedit']:
            raise RuntimeError('english_e_not_received_as_plain_text')
        result = backend.set_chinese(initial, True)
        time.sleep(.3)
        state = backend.snapshot()
        report['return_chinese'] = {
            'ok': result.ok, 'chinese': state.chinese, 'is_pinyin': state.is_pinyin,
            'same_layout': state.layout == initial.layout,
            'same_target': state.target_key == initial.target_key}
        if not (result.ok and state.chinese is True and state.is_pinyin is True
                and state.target_key == initial.target_key):
            raise RuntimeError('return_to_chinese_failed')
        report['status'] = 'passed'
    except Exception as error:
        report['reason'] = type(error).__name__ + ': ' + str(error)
    finally:
        try:
            if changed:
                report['restored'] = False
                if owns_target():
                    editor = editor_state()
                    if editor['preedit']:
                        press(0x1b)  # Cancel only this owned test's leftover composition.
                        time.sleep(.1)
                    backend._set(initial, IMC_SETCONVERSIONMODE, initial.conversion)
                    backend._set(initial, IMC_SETOPENSTATUS, int(initial.open_status))
                    state = backend.snapshot()
                    report['restored'] = (
                        state.target_key == initial.target_key
                        and state.conversion == initial.conversion
                        and state.open_status == initial.open_status)
                if not report['restored']:
                    report['status'] = 'failed'
                    report.setdefault('reason', 'test_context_not_restored')
        finally:
            backend.close()
            try:
                process.stdin.write('close\n')
                process.stdin.flush()
                process.wait(timeout=4)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    process.terminate()  # Only the exact owned child process.
                    process.wait(timeout=2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        child_window()
        return 0
    report = check()
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + '\n', encoding='utf-8')
    print(output)
    return 1 if report['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
