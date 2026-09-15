"""System-aware application palettes and shared widget styling."""

import sys

from PyQt5.QtCore import QAbstractNativeEventFilter, QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt5.QtWidgets import QWidget
from PyQt5 import sip


THEME_COLORS = {
    "background": "#171B22",
    "surface": "#232A35",
    "input": "#1C222B",
    "text": "#E8EDF3",
    "muted": "#A0AABA",
    "accent": "#85BAFF",
    "success": "#7BDCAB",
    "danger": "#FF9696",
    "highlight": "#315982",
    "highlight_text": "#FFFFFF",
    "border": "#465263",
    "disabled": "#818B9B",
    "keycap": "#2A3341",
    "keycap_shadow": "#10151C",
    "panel": "#1D232D",
}

THEMES = {
    "dark": dict(THEME_COLORS),
    "light": {
        "background": "#F2F5F9",
        "surface": "#FFFFFF",
        "input": "#FFFFFF",
        "text": "#243044",
        "muted": "#66758A",
        "accent": "#245DA8",
        "success": "#087852",
        "danger": "#C2344D",
        "highlight": "#DBEAFE",
        "highlight_text": "#193B64",
        "border": "#CFD8E5",
        "disabled": "#8793A5",
        "keycap": "#FFFFFF",
        "keycap_shadow": "#BDC9D9",
        "panel": "#E7EDF5",
    },
}
THEME_MODES = ("system", "light", "dark")


def _set_windows_titlebar(hwnd, dark):
    """Theme an existing HWND; unsupported DWM attributes are harmless."""
    import ctypes
    from ctypes import wintypes

    try:
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        # HWND is pointer-sized on 64-bit Windows, unlike the default c_int.
        dwm.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p,
                        wintypes.DWORD]
        dwm.restype = wintypes.LONG
        value = wintypes.BOOL(bool(dark))
        result = dwm(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        if result != 0:
            # Windows 10 before 20H1 used attribute 19 for this preference.
            result = dwm(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
        if sys.getwindowsversion().build >= 22000:
            colors = THEMES['dark' if dark else 'light']
            for attribute, color_name in ((35, 'background'), (36, 'text')):
                color = QColor(colors[color_name])
                colorref = wintypes.DWORD(color.red() | (color.green() << 8) |
                                          (color.blue() << 16))
                dwm(hwnd, attribute, ctypes.byref(colorref), ctypes.sizeof(colorref))
        return result == 0
    except (AttributeError, OSError, ValueError):
        return False


class NativeTitlebarTheme(QObject):
    """Follow Qt top-level lifetimes without creating native windows."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._applying = False
        app.installEventFilter(self)

    def applyWindow(self, widget):
        if (self._applying or sys.platform != 'win32' or
                self.app.platformName() != 'windows' or
                not isinstance(widget, QWidget) or sip.isdeleted(widget)):
            return
        if (not widget.isWindow() or widget.windowType() not in
                (Qt.Window, Qt.Dialog, Qt.Tool) or
                widget.windowFlags() & Qt.FramelessWindowHint or
                not widget.testAttribute(Qt.WA_WState_Created)):
            return
        # effectiveWinId does not force creation, unlike winId(). A WinIdChange
        # can also signal destruction; never recreate that HWND from a filter.
        native_id = widget.effectiveWinId()
        if not native_id:
            return
        hwnd = int(native_id)
        self._applying = True
        try:
            _set_windows_titlebar(hwnd, self.app.property('resolvedTheme') == 'dark')
        finally:
            self._applying = False

    def refresh(self):
        for widget in self.app.topLevelWidgets():
            self.applyWindow(widget)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Show, QEvent.WinIdChange):
            self.applyWindow(watched)
        return False


def _remember_system_palette(app):
    if not hasattr(app, "_morse_system_palette"):
        app._morse_system_palette = QPalette(app.palette())


def _windows_ui_font():
    """Read the actual Windows message font in points, independent of DPI."""
    import ctypes
    from ctypes import wintypes

    class LogFont(ctypes.Structure):
        _fields_ = [
            (name, wintypes.LONG) for name in
            ("height", "width", "escapement", "orientation", "weight")
        ] + [
            (name, wintypes.BYTE) for name in
            ("italic", "underline", "strike_out", "charset", "out_precision",
             "clip_precision", "quality", "pitch_and_family")
        ] + [("face_name", wintypes.WCHAR * 32)]

    class NonClientMetrics(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.UINT),
            ("border_width", ctypes.c_int),
            ("scroll_width", ctypes.c_int),
            ("scroll_height", ctypes.c_int),
            ("caption_width", ctypes.c_int),
            ("caption_height", ctypes.c_int),
            ("caption_font", LogFont),
            ("small_caption_width", ctypes.c_int),
            ("small_caption_height", ctypes.c_int),
            ("small_caption_font", LogFont),
            ("menu_width", ctypes.c_int),
            ("menu_height", ctypes.c_int),
            ("menu_font", LogFont),
            ("status_font", LogFont),
            ("message_font", LogFont),
            ("padded_border_width", ctypes.c_int),
        ]

    try:
        metrics = NonClientMetrics()
        metrics.size = ctypes.sizeof(metrics)
        read_metrics = ctypes.windll.user32.SystemParametersInfoForDpi
        read_metrics.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                 wintypes.UINT, wintypes.UINT]
        read_metrics.restype = wintypes.BOOL
        if not read_metrics(0x0029, metrics.size, ctypes.byref(metrics), 0, 96):
            return None
        native = metrics.message_font
        if native.height == 0:
            return None
        font = QFont(native.face_name)
        font.setPointSizeF(abs(native.height) * 72.0 / 96.0)
        font.setWeight(QFont.Bold if native.weight >= 600 else QFont.Normal)
        font.setItalic(bool(native.italic))
        return font
    except (AttributeError, OSError):
        return None


def _apply_ui_font(app):
    if not hasattr(app, "_morse_ui_font"):
        # Qt 5 can report a fallback font (e.g. SimSun 18 pt) even when the
        # Windows message font is 9 pt. Use the native font, then let Qt apply
        # the screen's DPI once. Theme changes must reuse this stable snapshot.
        font = _windows_ui_font() if sys.platform == "win32" else None
        if font is None:
            font = QFont(app.font())
        available = set(QFontDatabase().families())
        for family in (
            "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
            "Noto Sans CJK SC", "WenQuanYi Micro Hei",
        ):
            if family in available:
                font.setFamily(family)
                break
        app._morse_ui_font = QFont(font)
    app.setFont(QFont(app._morse_ui_font))


def detect_system_theme(app=None):
    """Read Windows' app preference, falling back to the native Qt palette."""
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value else "dark"
        except (ImportError, OSError):
            pass
    if app is not None:
        _remember_system_palette(app)
        palette = app._morse_system_palette
    else:
        palette = QPalette()
    return "dark" if palette.color(QPalette.Window).lightness() < 128 else "light"


def apply_theme(app, mode="system"):
    """Apply a light, dark, or system theme; return the resolved theme name."""
    if mode not in THEME_MODES:
        raise ValueError("Unknown theme mode: %s" % mode)
    _remember_system_palette(app)
    resolved = detect_system_theme(app) if mode == "system" else mode
    # Keep direct imports of this dictionary live when the theme changes.
    THEME_COLORS.clear()
    THEME_COLORS.update(THEMES[resolved])
    app.setStyle("Fusion")
    colors = THEME_COLORS
    palette = QPalette()
    roles = {
        QPalette.Window: "background",
        QPalette.WindowText: "text",
        QPalette.Base: "input",
        QPalette.AlternateBase: "surface",
        QPalette.ToolTipBase: "surface",
        QPalette.ToolTipText: "text",
        QPalette.Text: "text",
        QPalette.Button: "surface",
        QPalette.ButtonText: "text",
        QPalette.BrightText: "danger",
        QPalette.Link: "accent",
        QPalette.LinkVisited: "accent",
        QPalette.Highlight: "highlight",
        QPalette.HighlightedText: "highlight_text",
        QPalette.Light: "border",
        QPalette.Midlight: "surface",
        QPalette.Mid: "border",
        QPalette.Dark: "background",
        QPalette.Shadow: "keycap_shadow",
        QPalette.PlaceholderText: "muted",
    }
    for role, name in roles.items():
        palette.setColor(role, QColor(colors[name]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(colors["disabled"]))
    palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor(colors["surface"]))
    palette.setColor(QPalette.Disabled, QPalette.HighlightedText, QColor(colors["muted"]))
    app.setPalette(palette)

    _apply_ui_font(app)

    app.setStyleSheet("""
        QLabel, QGroupBox, QRadioButton, QCheckBox {
            color: %(text)s;
        }
        QGroupBox {
            border: 1px solid %(border)s;
            border-radius: 7px;
            margin-top: 0.8em;
            padding-top: 0.4em;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 3px;
        }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            background-color: %(input)s;
            color: %(text)s;
            border: 1px solid %(border)s;
            border-radius: 5px;
            padding: 4px 7px;
            selection-background-color: %(highlight)s;
            selection-color: %(highlight_text)s;
        }
        QLineEdit:focus, QComboBox:focus, QPushButton:focus,
        QSpinBox:focus, QDoubleSpinBox:focus {
            border-color: %(accent)s;
        }
        QComboBox QAbstractItemView {
            background-color: %(surface)s;
            color: %(text)s;
            border: 1px solid %(border)s;
            selection-background-color: %(highlight)s;
            selection-color: %(highlight_text)s;
        }
        QPushButton, QToolButton {
            background-color: %(surface)s;
            color: %(text)s;
            border: 1px solid %(border)s;
            border-radius: 5px;
            padding: 5px 10px;
        }
        QPushButton:hover, QToolButton:hover {
            border-color: %(accent)s;
            background-color: %(highlight)s;
            color: %(highlight_text)s;
        }
        QPushButton:pressed, QPushButton:checked,
        QToolButton:pressed, QToolButton:checked {
            background-color: %(highlight)s;
            color: %(highlight_text)s;
        }
        QPushButton:default {
            border-color: %(accent)s;
        }
        QFrame[role="keycap"], QPushButton[role="keycap"] {
            background-color: %(keycap)s;
            border: 1px solid %(border)s;
            border-bottom: 3px solid %(keycap_shadow)s;
            border-radius: 7px;
        }
        QFrame[role="keycap"][active="true"],
        QPushButton[role="keycap"]:checked {
            background-color: %(highlight)s;
            border-color: %(accent)s;
        }
        QFrame[role="panel"] {
            background-color: %(panel)s;
            border: 1px solid %(border)s;
            border-radius: 10px;
        }
        QLabel[role="muted"] { color: %(muted)s; }
        QScrollArea { border: none; background: transparent; }
        QScrollBar:vertical {
            background: %(background)s;
            width: 10px;
            margin: 0;
        }
        QScrollBar:horizontal {
            background: %(background)s;
            height: 10px;
            margin: 0;
        }
        QScrollBar::handle {
            background: %(border)s;
            border-radius: 4px;
            min-width: 24px;
            min-height: 24px;
        }
        QScrollBar::handle:hover { background: %(muted)s; }
        QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
        QLabel:disabled, QGroupBox:disabled, QRadioButton:disabled,
        QCheckBox:disabled, QLineEdit:disabled, QComboBox:disabled,
        QPushButton:disabled, QToolButton:disabled {
            color: %(disabled)s;
        }
        QLineEdit:disabled, QComboBox:disabled, QPushButton:disabled,
        QToolButton:disabled {
            background-color: %(background)s;
            border-color: %(surface)s;
        }
        QMenu {
            background-color: %(surface)s;
            color: %(text)s;
            border: 1px solid %(border)s;
            padding: 3px;
        }
        QMenu::item:selected {
            background-color: %(highlight)s;
            color: %(highlight_text)s;
        }
        QMenu::item:disabled {
            color: %(disabled)s;
        }
        QMenu::separator {
            height: 1px;
            background-color: %(border)s;
            margin: 4px 6px;
        }
        QToolTip {
            background-color: %(surface)s;
            color: %(text)s;
            border: 1px solid %(border)s;
            padding: 4px;
        }
        QStatusBar {
            background-color: %(surface)s;
            color: %(text)s;
        }
        QStatusBar::item {
            border: none;
        }
    """ % colors)
    app.setProperty("resolvedTheme", resolved)
    if not hasattr(app, '_morse_titlebar_theme'):
        app._morse_titlebar_theme = NativeTitlebarTheme(app)
    app._morse_titlebar_theme.refresh()
    return resolved


def apply_dark_theme(app):
    """Compatibility entry point for callers explicitly requesting dark mode."""
    return apply_theme(app, "dark")


# WM_SETTINGCHANGE, WM_THEMECHANGED, WM_DWMCOLORIZATIONCOLORCHANGED
_WINDOWS_THEME_MESSAGES = (0x001A, 0x031A, 0x0320)


class _WindowsThemeEventFilter(QAbstractNativeEventFilter):
    """Refresh when Windows reports a system color or theme change."""

    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def nativeEventFilter(self, eventType, message):
        try:
            manager = self.manager
            if manager is None or not message:
                return False, 0
            if eventType not in (b'windows_generic_MSG', b'windows_dispatcher_MSG'):
                return False, 0
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message in _WINDOWS_THEME_MESSAGES:
                QTimer.singleShot(0, manager._on_system_hint)
        except (TypeError, ValueError, OSError, RuntimeError):
            pass
        return False, 0


class ThemeManager(QObject):
    """Apply a saved preference and track changes to the system app theme."""

    themeChanged = pyqtSignal(str)

    def __init__(self, app, mode="system", parent=None):
        super().__init__(parent or app)
        self.app = app
        self._mode = None
        self._resolved_theme = None
        self._native_filter = None
        _remember_system_palette(app)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        if sys.platform == "win32" and app.platformName() == "windows":
            self._native_filter = _WindowsThemeEventFilter(self)
            app.installNativeEventFilter(self._native_filter)
            native = self._native_filter
            self.destroyed.connect(
                lambda *_args, application=app, filter=native:
                ThemeManager._drop_native_filter(application, filter))
        app.installEventFilter(self)
        self.set_mode(mode)

    @staticmethod
    def _drop_native_filter(app, native):
        if native is None:
            return
        native.manager = None
        try:
            app.removeNativeEventFilter(native)
        except RuntimeError:
            pass

    @property
    def mode(self):
        return self._mode

    @property
    def resolved_theme(self):
        return self._resolved_theme

    def _uses_theme_timer(self):
        return sys.platform != "win32"

    def _on_system_hint(self):
        if self._mode == "system":
            self.refresh()

    def eventFilter(self, watched, event):
        if (self._mode == "system" and watched is self.app and
                event.type() == QEvent.ApplicationPaletteChange):
            QTimer.singleShot(0, self._on_system_hint)
        return False

    def set_mode(self, mode):
        if mode not in THEME_MODES:
            raise ValueError("Unknown theme mode: %s" % mode)
        self._mode = mode
        if mode == "system" and self._uses_theme_timer():
            self._timer.start()
        else:
            self._timer.stop()
        self.refresh()

    def refresh(self):
        """Re-read the native preference; avoid restyling unchanged widgets."""
        resolved = detect_system_theme(self.app) if self._mode == "system" else self._mode
        if resolved != self._resolved_theme:
            apply_theme(self.app, resolved)
            self._resolved_theme = resolved
            self.themeChanged.emit(resolved)
