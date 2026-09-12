"""Opt-in per-user startup and one owned Windows global shortcut.

Importing this module does not write the registry or register a shortcut.
Native APIs are injectable so tests never modify the user's Windows session.
"""

import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading

from PyQt5.QtCore import QCoreApplication, QObject, QThread, Qt, pyqtSignal
from PyQt5.QtGui import QGuiApplication, QKeySequence


DEFAULT_GLOBAL_HOTKEY = 'Ctrl+Alt+Shift+M'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_VALUE = 'MorseWriter'
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 0x4D57


def show_guide_without_activation(window, *, keep_minimized=False,
                                  user32=None, platform_name=None):
    """Show/restore a guide above desktop windows without taking input focus.

    Call from the Qt GUI thread. Read the current HWND on every invocation:
    changing Qt window flags can recreate it. ``keep_minimized`` preserves a
    minimized guide while its frame changes. Native failures are logged and
    return False; there is deliberately no activating fallback on Windows.
    """
    window.setAttribute(Qt.WA_ShowWithoutActivating, True)
    native_windows = (platform_name or platform.system()) == 'Windows'
    # Qt's offscreen/minimal plugins expose synthetic IDs, not native HWNDs.
    # Smoke validation also keeps real Windows widgets off the user's screen.
    if (window.testAttribute(Qt.WA_DontShowOnScreen) or not native_windows
            or (user32 is None and QGuiApplication.platformName() != 'windows')):
        if keep_minimized:
            window.showMinimized()
        else:
            window.showNormal()
            window.raise_()
        return True

    if user32 is None:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                   ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL

    # Keep Qt visibility bookkeeping in sync without Qt's activating
    # showNormal()/restore path. Only restore minimized windows: applying
    # SW_SHOWNOACTIVATE to a maximized window would silently unmaximize its
    # native HWND while Qt still believes it is maximized.
    window.show()
    hwnd = int(window.winId())
    # SW_SHOWMINNOACTIVE also handles Qt's hidden showMinimized path, which
    # can ignore minimization when WA_ShowWithoutActivating is enabled.
    show_mode = 7 if keep_minimized else 4 if window.isMinimized() else 8
    # SW_SHOWMINNOACTIVE / SW_SHOWNOACTIVATE / SW_SHOWNA.
    user32.ShowWindow(hwnd, show_mode)  # Zero means previously hidden, not failure.
    if not user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0053):
        # HWND_TOPMOST; SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW.
        logging.warning('无法将码表置顶（Windows 错误 %s）。', ctypes.get_last_error())
        return False
    return True


def startup_command(executable=None, script_path=None, frozen=None):
    """Build a Windows argv command line, never a shell/batch command."""
    executable = os.path.abspath(executable or sys.executable)
    frozen = bool(getattr(sys, 'frozen', False)) if frozen is None else bool(frozen)
    if frozen:
        arguments = [executable, '--startup']
    else:
        pythonw = Path(executable).with_name('pythonw.exe')
        if Path(executable).name.lower() == 'python.exe' and pythonw.is_file():
            executable = str(pythonw)
        script_path = os.path.abspath(script_path or Path(__file__).with_name('MorseCodeGUI.py'))
        arguments = [executable, script_path, '--startup']
    # Match the installer Run entry even when the installation directory has
    # no spaces. Always quote argv[0]; quote the remaining argv normally.
    program = subprocess.list2cmdline(arguments[:1])
    if not program.startswith('"'):
        program = '"' + program + '"'
    return program + ' ' + subprocess.list2cmdline(arguments[1:])


class StartupRegistration:
    def __init__(self, executable=None, script_path=None, frozen=None, *,
                 registry=None, platform_name=None):
        self.supported = (platform_name or platform.system()) == 'Windows'
        self.command = startup_command(executable, script_path, frozen)
        self._registry = registry

    def _api(self):
        if not self.supported:
            raise RuntimeError('当前系统不支持此开机自启设置。')
        if self._registry is None:
            import winreg
            self._registry = winreg
        return self._registry

    def is_enabled(self):
        """Whether this exact application command is registered for this user."""
        if not self.supported:
            return False
        registry = self._api()
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_READ) as key:
                value, kind = registry.QueryValueEx(key, RUN_VALUE)
            return kind == registry.REG_SZ and value == self.command
        except FileNotFoundError:
            return False
        except OSError as error:
            raise RuntimeError('无法读取开机自启设置：' + str(error)) from error

    def set_enabled(self, enabled):
        """The only registry-writing entry point; call on a user preference change."""
        registry = self._api()
        try:
            if enabled:
                if len(self.command.encode('utf-16-le')) // 2 > 260:
                    raise ValueError('启动路径过长，无法写入 Windows 开机自启项；请将程序放在较短的路径下。')
                with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE) as key:
                    registry.SetValueEx(key, RUN_VALUE, 0, registry.REG_SZ, self.command)
            else:
                try:
                    with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE) as key:
                        registry.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        except OSError as error:
            raise RuntimeError('无法修改开机自启设置：' + str(error)) from error
        return bool(enabled)


_KEY_VKS = {
    Qt.Key_Escape: 0x1B, Qt.Key_Tab: 0x09, Qt.Key_Backtab: 0x09,
    Qt.Key_Backspace: 0x08, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D,
    Qt.Key_Insert: 0x2D, Qt.Key_Delete: 0x2E, Qt.Key_Pause: 0x13,
    Qt.Key_Print: 0x2C, Qt.Key_Home: 0x24, Qt.Key_End: 0x23,
    Qt.Key_Left: 0x25, Qt.Key_Up: 0x26, Qt.Key_Right: 0x27, Qt.Key_Down: 0x28,
    Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22, Qt.Key_Space: 0x20,
    Qt.Key_CapsLock: 0x14, Qt.Key_NumLock: 0x90, Qt.Key_ScrollLock: 0x91,
}
# Qt's portable key names describe the US key legends used by this program.
_PUNCTUATION_VKS = {';': 0xBA, '=': 0xBB, ',': 0xBC, '-': 0xBD, '.': 0xBE,
                    '/': 0xBF, '`': 0xC0, '[': 0xDB, '\\': 0xDC, ']': 0xDD, "'": 0xDE}
_SHIFTED_KEYS = dict(zip('!@#$%^&*()', '1234567890'))
_SHIFTED_KEYS.update(dict(zip(':<>?_+{}|~"', ';,./-=[]\\`\'')))


def parse_hotkey(sequence):
    """Return (portable_text, MOD_* flags, keyboard VK) for one chord.

    Bare typing keys and Shift-only typing combinations are rejected because
    RegisterHotKey would consume them in every application. Function keys can
    be used alone, except the Windows-reserved debugger key F12.
    """
    key_sequence = (QKeySequence(sequence) if isinstance(sequence, QKeySequence)
                    else QKeySequence.fromString(str(sequence), QKeySequence.PortableText))
    if key_sequence.isEmpty() or key_sequence.count() != 1:
        raise ValueError('请选择一组快捷键，例如 Ctrl+Alt+M；不支持连续多组按键。')
    raw = int(key_sequence[0])
    if raw == int(Qt.Key_unknown):
        raise ValueError('无法识别这组快捷键，请重新选择。')
    modifiers = 0
    for qt_modifier, native_modifier in ((Qt.ControlModifier, MOD_CONTROL),
                                         (Qt.AltModifier, MOD_ALT),
                                         (Qt.ShiftModifier, MOD_SHIFT),
                                         (Qt.MetaModifier, MOD_WIN)):
        if raw & int(qt_modifier):
            modifiers |= native_modifier
    if raw & int(Qt.GroupSwitchModifier):
        raise ValueError('全局快捷键不支持 AltGr，请使用 Ctrl、Alt 或 Windows 键组合。')
    key = raw & ~int(Qt.KeyboardModifierMask)
    function_key = int(Qt.Key_F1) <= key <= int(Qt.Key_F24)
    if key == int(Qt.Key_F12):
        raise ValueError('F12 由 Windows 调试器保留，请换一个快捷键。')
    if not function_key and not modifiers & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        raise ValueError('请加入 Ctrl、Alt 或 Windows 键，避免占用普通输入按键。')
    if raw & int(Qt.KeypadModifier):
        if ord('0') <= key <= ord('9'):
            vk = 0x60 + key - ord('0')
        else:
            raise ValueError('此数字小键盘组合暂不支持，请使用主键盘组合。')
    elif function_key:
        vk = 0x70 + key - int(Qt.Key_F1)
    elif ord('A') <= key <= ord('Z') or ord('0') <= key <= ord('9'):
        vk = key
    elif key in _KEY_VKS:
        vk = _KEY_VKS[key]
        if key == int(Qt.Key_Backtab):
            modifiers |= MOD_SHIFT
    else:
        character = chr(key) if 0 <= key <= 0x10FFFF else ''
        if character in _SHIFTED_KEYS:
            modifiers |= MOD_SHIFT
            character = _SHIFTED_KEYS[character]
        if character in _PUNCTUATION_VKS:
            vk = _PUNCTUATION_VKS[character]
        elif character in '0123456789' and character:
            vk = ord(character)
        else:
            raise ValueError('此按键不能用作全局快捷键，请选择字母、数字、功能键或导航键。')
    return key_sequence.toString(QKeySequence.PortableText), modifiers, vk


class WindowsHotkeyLoop:
    """Own registration and message delivery on the thread that calls run()."""
    def __init__(self, sequence, modifiers, vk, activated, ready=None, *,
                 stop_event=None, user32=None, kernel32=None):
        if user32 is None:
            if platform.system() != 'Windows':
                raise RuntimeError('当前系统不支持此全局快捷键。')
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.sequence, self.modifiers, self.vk = sequence, modifiers, vk
        self.activated, self.ready = activated, ready
        self.user32, self.kernel32 = user32, kernel32
        self._stopping = stop_event or threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._thread_id = None
        self._registered = False
        self._configure_api()

    def _configure_api(self):
        signatures = (
            ('RegisterHotKey', [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
            ('UnregisterHotKey', [wintypes.HWND, ctypes.c_int], wintypes.BOOL),
            ('PeekMessageW', [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                              wintypes.UINT, wintypes.UINT], wintypes.BOOL),
            ('TranslateMessage', [ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
            ('DispatchMessageW', [ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t),
            ('PostThreadMessageW', [wintypes.DWORD, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t], wintypes.BOOL),
            ('MsgWaitForMultipleObjects', [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
                                          wintypes.BOOL, wintypes.DWORD, wintypes.DWORD], wintypes.DWORD),
        )
        for name, arguments, result in signatures:
            function = getattr(self.user32, name)
            function.argtypes, function.restype = arguments, result
        self.kernel32.GetCurrentThreadId.argtypes = []
        self.kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    def run(self):
        message = wintypes.MSG()
        # Create the queue before publishing its ID, so an early stop cannot
        # lose its wakeup. The bounded wait also handles a failed wakeup post.
        self.user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        with self._lifecycle_lock:
            self._thread_id = self.kernel32.GetCurrentThreadId()
        try:
            if self._stopping.is_set():
                return
            self._registered = bool(self.user32.RegisterHotKey(
                None, HOTKEY_ID, self.modifiers | MOD_NOREPEAT, self.vk))
            if not self._registered:
                code = ctypes.get_last_error()
                if code == 1409:
                    raise RuntimeError(f'快捷键 {self.sequence} 已被系统或其他程序占用，请换一组按键。')
                raise RuntimeError(f'无法注册快捷键 {self.sequence}（Windows 错误 {code}），请检查是否已被占用。')
            if self._stopping.is_set():
                return
            if self.ready:
                self.ready(self.sequence)
            while not self._stopping.is_set():
                while self.user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                    if self._stopping.is_set() or message.message == WM_QUIT:
                        return
                    if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                        self.activated()
                    else:
                        self.user32.TranslateMessage(ctypes.byref(message))
                        self.user32.DispatchMessageW(ctypes.byref(message))
                if self._stopping.is_set():
                    break
                # Zero handles + QS_ALLINPUT: wake immediately for a hotkey,
                # or every 100 ms to observe shutdown if PostThreadMessage fails.
                result = self.user32.MsgWaitForMultipleObjects(0, None, False, 100, 0x04FF)
                if result == 0xFFFFFFFF:
                    raise RuntimeError('全局快捷键消息循环失败。')
        finally:
            try:
                if self._registered and not self.user32.UnregisterHotKey(None, HOTKEY_ID):
                    logging.error('释放全局快捷键失败：%s', self.sequence)
            finally:
                self._registered = False
                with self._lifecycle_lock:
                    self._thread_id = None

    def stop(self):
        self._stopping.set()
        with self._lifecycle_lock:
            if self._thread_id is not None:
                self.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)


class _HotkeyThread(QThread):
    activated = pyqtSignal()
    ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, parsed):
        super().__init__()
        self.parsed = parsed
        self._stop_requested = threading.Event()
        self._loop = None

    def run(self):
        try:
            self._loop = WindowsHotkeyLoop(*self.parsed, self.activated.emit,
                                           self.ready.emit, stop_event=self._stop_requested)
            self._loop.run()
        except Exception as error:
            logging.exception('全局快捷键不可用')
            if not self._stop_requested.is_set():
                self.error.emit(str(error))
        finally:
            self._loop = None

    def stop(self):
        self._stop_requested.set()
        loop = self._loop
        if loop is not None:
            loop.stop()
        if self.isRunning() and QThread.currentThread() != self:
            self.wait()


class GlobalHotkey(QObject):
    activated = pyqtSignal()
    ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, parent=None, *, thread_factory=None, platform_name=None):
        super().__init__(parent)
        self.supported = (platform_name or platform.system()) == 'Windows'
        self.sequence = ''
        self.active_sequence = ''
        self._thread = None
        self._thread_factory = thread_factory or _HotkeyThread
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    def set_sequence(self, sequence=DEFAULT_GLOBAL_HOTKEY):
        """Start/rebind a shortcut; success is confirmed asynchronously by ready.

        Empty text disables the shortcut. Validation failure keeps the existing
        binding. A native conflict reports error and leaves no active binding.
        """
        if not sequence:
            self.stop()
            self.sequence = ''
            self.ready.emit('')
            return True
        if not self.supported:
            self.error.emit('当前系统不支持此全局快捷键。')
            return False
        try:
            parsed = parse_hotkey(sequence)
        except ValueError as error:
            self.error.emit(str(error))
            return False
        if parsed[0] == self.sequence and self._thread is not None:
            if self.active_sequence == parsed[0]:
                # Reapplying the working binding also clears a previous
                # validation error in the UI. Pending registration is not ready.
                self.ready.emit(parsed[0])
            return True
        self.stop()
        self.sequence = parsed[0]
        thread = self._thread_factory(parsed)
        self._thread = thread
        thread.activated.connect(self._activated)
        thread.ready.connect(self._ready)
        thread.error.connect(self._error)
        thread.finished.connect(self._finished)
        # A parent may destroy this controller without an explicit stop.
        # Stop the independent worker before losing its Python owner.
        self.destroyed.connect(thread.stop)
        self.destroyed.connect(thread.deleteLater)
        thread.start()
        return True

    def _activated(self):
        if self.sender() is self._thread:
            self.activated.emit()

    def _ready(self, sequence):
        if self.sender() is self._thread:
            self.active_sequence = sequence
            self.ready.emit(sequence)

    def _error(self, message):
        if self.sender() is self._thread:
            self.active_sequence = ''
            self.error.emit(message)

    def _finished(self):
        thread = self.sender()
        if thread is self._thread:
            self._thread = None
            self.active_sequence = ''
        if thread is not None:
            try:
                self.destroyed.disconnect(thread.stop)
                self.destroyed.disconnect(thread.deleteLater)
            except (TypeError, RuntimeError):
                pass
            thread.deleteLater()

    def stop(self):
        thread, self._thread = self._thread, None
        self.active_sequence = ''
        if thread is None:
            return
        thread.stop()
        for signal, handler in ((thread.activated, self._activated), (thread.ready, self._ready),
                                (thread.error, self._error), (thread.finished, self._finished),
                                (self.destroyed, thread.stop), (self.destroyed, thread.deleteLater)):
            try:
                signal.disconnect(handler)
            except (TypeError, RuntimeError):
                pass
        thread.deleteLater()
