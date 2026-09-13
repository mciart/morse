"""Bounded, foreground-targeted Microsoft Pinyin mode access.

No input hooks, key simulation, focus changes, registry writes, process injection
or calls to a foreign HIMC. The target thread's default IME window owns the mode;
the calling thread's TSF ACTIVE flag/compartments are deliberately never used.
Modern TSF profiles can share a generic HKL. Such a layout is only classified
when its enabled keyboard profile is unambiguous; otherwise mode is unknown.

Native contracts:
https://learn.microsoft.com/windows/win32/api/immdev/nf-immdev-immgetdefaultimewnd
https://learn.microsoft.com/windows/win32/api/msctf/ns-msctf-tf_inputprocessorprofile
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-sendmessagetimeoutw
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, replace
import platform
import uuid


WM_IME_CONTROL = 0x0283
IMC_GETCONVERSIONMODE = 0x0001
IMC_SETCONVERSIONMODE = 0x0002
IMC_GETOPENSTATUS = 0x0005
IMC_SETOPENSTATUS = 0x0006
IME_CMODE_NATIVE = 0x0001
PINYIN_CLSID = '81d4e9c9-1d3b-41bc-9e6c-4b40bf79e35e'
PINYIN_PROFILE = 'fa550b04-5ad7-411f-a5ac-ca038ec515d7'
KEYBOARD_CATEGORY = '34745c63-b2f0-4784-8b67-5e12c8701a31'


@dataclass(frozen=True)
class ImeState:
    foreground: int = 0
    focus: int = 0
    thread_id: int = 0
    process_id: int = 0
    layout: int = 0
    ime_window: int = 0
    is_pinyin: bool | None = None
    chinese: bool | None = None
    open_status: bool | None = None
    conversion: int | None = None
    reason: str = ''

    @property
    def target_key(self):
        return (self.foreground, self.focus, self.thread_id, self.process_id,
                self.layout, self.ime_window)


@dataclass(frozen=True)
class ImeSetResult:
    ok: bool
    state: ImeState | None
    reason: str = ''


@dataclass(frozen=True)
class InputProfile:
    profile_type: int
    language: int
    clsid: str = ''
    profile: str = ''
    category: str = KEYBOARD_CATEGORY
    substitute: int = 0
    layout: int = 0
    enabled: bool = False

    @property
    def is_pinyin(self):
        return (self.profile_type == 1 and self.clsid.lower() == PINYIN_CLSID
                and self.profile.lower() == PINYIN_PROFILE)


class ImeUnavailable(RuntimeError):
    """The native API could not provide a trustworthy result."""


def classify_pinyin(layout, description, ime_file, profiles):
    """Return a proven identity, never infer the IME from language alone.

    Profiles describe enabled input methods, NOT the caller's active method.
    The generic Simplified Chinese HKL is shared by modern TIPs, so every
    enabled keyboard profile (including non-IME layouts) must be considered.
    """
    layout &= 0xffffffff
    if layout & 0xffff != 0x0804:
        return False, 'other_language'
    name = description.strip().casefold()
    filename = ime_file.replace('\\', '/').rsplit('/', 1)[-1].casefold()
    if name in ('microsoft pinyin', '微软拼音', '微軟拼音', '微软拼音输入法'):
        return True, 'ime_identity'
    if name or filename:
        return False, 'other_ime'
    candidates = [p for p in profiles if p.language == 0x0804
                  and p.category.lower() == KEYBOARD_CATEGORY]
    substitutes = [p for p in candidates if p.profile_type == 1
                   and p.substitute and p.substitute & 0xffffffff == layout]
    if len(substitutes) == 1:
        return substitutes[0].is_pinyin, 'substitute_profile'
    if substitutes:
        return None, 'ambiguous_profile'
    if layout != 0x08040804:
        return None, 'unknown_layout'
    enabled = [p for p in candidates if p.enabled]
    if len(enabled) == 1:
        return enabled[0].is_pinyin, 'single_enabled_profile'
    return None, 'ambiguous_profile' if enabled else 'unknown_profile'


class NativeImeBackend:
    """Construct and close in the same worker thread when using native APIs.

    All foreign-window messages have a timeout (default 60 ms each). Failures
    and ambiguous profiles remain unknown; callers must not retry writes in a
    polling loop. A successful write includes a readback from the same target.
    """
    def __init__(self, api=None, *, platform_name=None, timeout_ms=60):
        self.supported = api is not None or (platform_name or platform.system()) == 'Windows'
        self.timeout_ms = max(10, min(200, int(timeout_ms)))
        self._api = api
        self._closed = False

    @property
    def api(self):
        if self._api is None:
            self._api = _WindowsImeApi()
        return self._api

    def close(self):
        self._closed = True
        if self._api is not None:
            self._api.close()

    @staticmethod
    def capture_target():
        """Capture a request's target now; no messages, COM or mode reads."""
        if platform.system() != 'Windows':
            return ImeState(reason='unsupported')
        try:
            api = _WindowsImeApi(with_profiles=False)
            state = api.target()
            if not state.foreground or not state.focus or not state.thread_id:
                return replace(state, reason='no_focus')
            if not state.layout:
                return replace(state, reason='no_keyboard_layout')
            return state
        except (ImeUnavailable, OSError) as exc:
            return ImeState(reason=str(exc) or 'focus_unavailable')

    @staticmethod
    def target_matches(state):
        """Fast identity-only guard; no messages, COM or input-method writes."""
        if not isinstance(state, ImeState) or not state.focus:
            return False
        current = NativeImeBackend.capture_target()
        return not current.reason and current.target_key == state.target_key

    def snapshot(self):
        if not self.supported or self._closed:
            return ImeState(reason='unsupported' if not self.supported else 'closed')
        state = ImeState()
        try:
            state = self.api.target()
            if not state.foreground or not state.focus or not state.thread_id:
                return replace(state, reason='no_focus')
            if not state.layout:
                return replace(state, reason='no_keyboard_layout')
            description, filename = self.api.ime_identity(state.layout)
            profiles = ()
            if state.layout & 0xffff == 0x0804 and not description and not filename:
                profiles = self.api.profiles(0x0804)
            is_pinyin, reason = classify_pinyin(state.layout, description, filename, profiles)
            state = replace(state, is_pinyin=is_pinyin, reason=reason)
            if not is_pinyin:
                return state
            if not state.ime_window:
                return replace(state, reason='no_ime_window')
            opened = self.api.control(state.ime_window, IMC_GETOPENSTATUS, 0, self.timeout_ms)
            if opened not in (0, 1):
                return replace(state, reason='invalid_open_status')
            conversion = self.api.control(state.ime_window, IMC_GETCONVERSIONMODE, 0, self.timeout_ms)
            if conversion < 0 or conversion > 0xffff:
                return replace(state, reason='invalid_conversion')
            if self.api.target().target_key != state.target_key:
                return replace(state, reason='target_changed')
            return replace(state, open_status=bool(opened), conversion=conversion,
                           chinese=bool(opened and conversion & IME_CMODE_NATIVE), reason='')
        except (ImeUnavailable, OSError) as exc:
            return replace(state, chinese=None, reason=str(exc) or 'native_error')

    def set_chinese(self, state, chinese):
        if not isinstance(state, ImeState) or not isinstance(chinese, bool):
            raise ValueError('Expected ImeState and bool')
        current = self.snapshot()
        if current.target_key != state.target_key:
            return ImeSetResult(False, current, 'target_changed')
        if current.is_pinyin is not True or current.chinese is None:
            return ImeSetResult(False, current, current.reason or 'unsupported_target')
        if current.chinese == chinese:
            return ImeSetResult(True, current)
        try:
            if not chinese:
                # Closing Microsoft Pinyin's input context also finalizes an
                # active composition as its original spelling. Merely clearing
                # NATIVE can leave candidates active or be rejected while they
                # are open. Do not synthesize Enter/Space/Shift in the target.
                result = self._set(current, IMC_SETOPENSTATUS, 0)
                if result:
                    return ImeSetResult(False, self.snapshot(), 'set_close_rejected')
            else:
                if not current.open_status:
                    result = self._set(current, IMC_SETOPENSTATUS, 1)
                    if result:
                        return ImeSetResult(False, self.snapshot(), 'set_open_rejected')
                    current = self.snapshot()
                    if (current.target_key != state.target_key or current.is_pinyin is not True
                            or current.chinese is None or not current.open_status):
                        return ImeSetResult(False, current, current.reason or 'open_not_confirmed')
                conversion = current.conversion | IME_CMODE_NATIVE
                if conversion != current.conversion:
                    result = self._set(current, IMC_SETCONVERSIONMODE, conversion)
                    if result:
                        return ImeSetResult(False, self.snapshot(), 'set_conversion_rejected')
            confirmed = self.snapshot()
            if confirmed.target_key != state.target_key:
                return ImeSetResult(False, confirmed, 'target_changed')
            ok = confirmed.is_pinyin is True and confirmed.chinese is chinese
            return ImeSetResult(ok, confirmed, '' if ok else (
                confirmed.reason or 'mode_not_confirmed'))
        except (ImeUnavailable, OSError) as exc:
            return ImeSetResult(False, self.snapshot(), str(exc) or 'native_error')

    def _set(self, state, command, value):
        # Recheck immediately before each mutation, including after opening an
        # initially closed IME. Never write a stale application's IME window.
        if self.api.target().target_key != state.target_key:
            raise ImeUnavailable('target_changed')
        return self.api.control(state.ime_window, command, value, self.timeout_ms)


class _GUID(ctypes.Structure):
    # DWORD alignment is essential inside TF_INPUTPROCESSORPROFILE.
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)

    def __str__(self):
        return str(uuid.UUID(bytes_le=bytes(self)))


class _Profile(ctypes.Structure):
    _fields_ = [('profile_type', wintypes.DWORD), ('language', wintypes.WORD),
                ('clsid', _GUID), ('profile', _GUID), ('category', _GUID),
                ('substitute', wintypes.HKL), ('caps', wintypes.DWORD),
                ('layout', wintypes.HKL), ('flags', wintypes.DWORD)]


class _GUIThreadInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                ('active', wintypes.HWND), ('focus', wintypes.HWND),
                ('capture', wintypes.HWND), ('menu_owner', wintypes.HWND),
                ('move_size', wintypes.HWND), ('caret', wintypes.HWND),
                ('caret_rect', wintypes.RECT)]


class _WindowsImeApi:
    def __init__(self, *, with_profiles=True):
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.imm32 = ctypes.WinDLL('imm32', use_last_error=True)
        self._com_owned = False
        u, i = self.user32, self.imm32
        u.GetForegroundWindow.argtypes, u.GetForegroundWindow.restype = [], wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUIThreadInfo)]
        u.GetGUIThreadInfo.restype = wintypes.BOOL
        u.GetKeyboardLayout.argtypes, u.GetKeyboardLayout.restype = [wintypes.DWORD], wintypes.HKL
        u.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                        wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                        ctypes.POINTER(ctypes.c_size_t)]
        u.SendMessageTimeoutW.restype = wintypes.LPARAM
        i.ImmGetDefaultIMEWnd.argtypes, i.ImmGetDefaultIMEWnd.restype = [wintypes.HWND], wintypes.HWND
        for function in (i.ImmGetDescriptionW, i.ImmGetIMEFileNameW):
            function.argtypes = [wintypes.HKL, wintypes.LPWSTR, wintypes.UINT]
            function.restype = wintypes.UINT
        if not with_profiles:
            return
        o = self.ole32 = ctypes.WinDLL('ole32', use_last_error=True)
        o.CoInitializeEx.argtypes, o.CoInitializeEx.restype = [ctypes.c_void_p, wintypes.DWORD], ctypes.c_long
        o.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        o.CoCreateInstance.restype = ctypes.c_long
        o.CoUninitialize.argtypes, o.CoUninitialize.restype = [], None
        initialized = o.CoInitializeEx(None, 2)
        self._com_owned = initialized in (0, 1)
        if initialized < 0 and initialized & 0xffffffff != 0x80010106:
            raise ImeUnavailable('profile_api_unavailable')

    def close(self):
        if self._com_owned:
            self._com_owned = False
            self.ole32.CoUninitialize()

    def target(self):
        foreground = int(self.user32.GetForegroundWindow() or 0)
        if not foreground:
            return ImeState()
        process = wintypes.DWORD()
        thread = self.user32.GetWindowThreadProcessId(foreground, ctypes.byref(process))
        info = _GUIThreadInfo()
        info.cbSize = ctypes.sizeof(info)
        if not thread or not self.user32.GetGUIThreadInfo(thread, ctypes.byref(info)):
            raise ImeUnavailable('focus_unavailable')
        focus = int(info.focus or 0)
        if focus:
            focus_process = wintypes.DWORD()
            focus_thread = self.user32.GetWindowThreadProcessId(focus, ctypes.byref(focus_process))
            if not focus_thread:
                raise ImeUnavailable('focus_unavailable')
            thread, process = focus_thread, focus_process
        layout = int(self.user32.GetKeyboardLayout(thread) or 0)
        ime_window = int(self.imm32.ImmGetDefaultIMEWnd(focus) or 0) if focus else 0
        return ImeState(foreground, focus, thread, process.value, layout, ime_window)

    def ime_identity(self, layout):
        description, filename = ctypes.create_unicode_buffer(260), ctypes.create_unicode_buffer(260)
        self.imm32.ImmGetDescriptionW(layout, description, 260)
        self.imm32.ImmGetIMEFileNameW(layout, filename, 260)
        return description.value, filename.value

    def control(self, hwnd, command, value, timeout_ms):
        result = ctypes.c_size_t()
        ctypes.set_last_error(0)
        # BLOCK | ABORTIFHUNG | ERRORONEXIT. Do not use NOTIMEOUTIFNOTHUNG.
        ok = self.user32.SendMessageTimeoutW(hwnd, WM_IME_CONTROL, command, value,
                                            0x23, timeout_ms, ctypes.byref(result))
        if not ok:
            error = ctypes.get_last_error()
            raise ImeUnavailable('access_denied' if error == 5 else 'ime_timeout')
        return result.value

    @staticmethod
    def _com_call(pointer, index, argtypes, *args):
        vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        function = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])
        return function(pointer, *args)

    def profiles(self, language):
        manager, enumerator = ctypes.c_void_p(), ctypes.c_void_p()
        clsid = _GUID.parse('33c53a50-f456-4884-b049-85fd643ecfed')
        iid = _GUID.parse('71c6e74c-0f28-11d8-a82a-00065b84435c')
        result = []
        try:
            hr = self.ole32.CoCreateInstance(ctypes.byref(clsid), None, 1,
                                            ctypes.byref(iid), ctypes.byref(manager))
            if hr < 0 or not manager:
                raise ImeUnavailable('profile_api_unavailable')
            hr = self._com_call(manager, 6, [wintypes.WORD, ctypes.POINTER(ctypes.c_void_p)],
                                language, ctypes.byref(enumerator))
            if hr < 0 or not enumerator:
                raise ImeUnavailable('profile_api_unavailable')
            # A bounded enumeration also protects against a broken COM provider.
            for _ in range(256):
                profile, fetched = _Profile(), wintypes.ULONG()
                hr = self._com_call(enumerator, 4,
                                    [wintypes.ULONG, ctypes.POINTER(_Profile), ctypes.POINTER(wintypes.ULONG)],
                                    1, ctypes.byref(profile), ctypes.byref(fetched))
                if hr < 0:
                    raise ImeUnavailable('profile_api_unavailable')
                if not fetched.value:
                    return tuple(result)
                result.append(InputProfile(profile.profile_type, profile.language,
                                           str(profile.clsid), str(profile.profile), str(profile.category),
                                           int(profile.substitute or 0), int(profile.layout or 0),
                                           bool(profile.flags & 2)))
                if hr == 1:
                    return tuple(result)
            raise ImeUnavailable('profile_list_too_large')
        finally:
            if enumerator:
                self._com_call(enumerator, 2, [])
            if manager:
                self._com_call(manager, 2, [])
