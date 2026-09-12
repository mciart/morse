"""Optional Windows screen-composition regression; run explicitly, never on import.

Opens only a solid test backdrop and the real guide, without the main application,
input hooks, audio, registry access or user-config writes. Mouse events stay inside
Qt. Desktop pixels are sampled only after checking that this process owns the
test region. Exit codes: 0 passed, 1 failed, 2 unavailable desktop/platform.
--allow-unavailable changes only the last exit code; it never reports a pass.
"""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = (229, 16, 160)


class NativeDesktopUnavailable(RuntimeError):
    """The independent backdrop cannot be sampled; the guide was not tested."""


class OwnedRegionUnavailable(RuntimeError):
    """Capture is blocked; only initial backdrop calibration may skip this."""


def windows_api():
    api = ctypes.WinDLL('user32', use_last_error=True)
    signatures = (
        ('OpenInputDesktop', [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        ('CloseDesktop', [wintypes.HANDLE], wintypes.BOOL),
        ('GetWindowRect', [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
        ('WindowFromPoint', [wintypes.POINT], wintypes.HWND),
        ('GetWindowThreadProcessId', [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        ('IsWindowVisible', [wintypes.HWND], wintypes.BOOL),
        ('IsIconic', [wintypes.HWND], wintypes.BOOL),
        ('GetDpiForWindow', [wintypes.HWND], wintypes.UINT),
        ('GetThreadDpiAwarenessContext', [], wintypes.HANDLE),
        ('GetAwarenessFromDpiAwarenessContext', [wintypes.HANDLE], ctypes.c_int),
    )
    for name, arguments, result in signatures:
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    return api


def check_native(report, save_images=False):
    if sys.platform != 'win32':
        return dict(status='unavailable', skipped=True, reason='Windows desktop required'), 2
    api = windows_api()
    desktop = api.OpenInputDesktop(0, False, 1)  # DESKTOP_READOBJECTS; read only.
    if not desktop:
        return dict(status='unavailable', skipped=True, reason='Input desktop unavailable',
                    windows_error=ctypes.get_last_error()), 2
    api.CloseDesktop(desktop)

    os.environ['QT_QPA_PLATFORM'] = 'windows'
    sys.path.insert(0, str(ROOT))
    from PyQt5 import sip
    from PyQt5.QtCore import (Qt, QEvent, QEventLoop, QPoint, QPointF, QTimer,
                             QtWarningMsg, QtCriticalMsg, QtFatalMsg, qInstallMessageHandler)
    from PyQt5.QtGui import QFont, QFontMetrics, QMouseEvent
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication, QWidget
    from tools.generate_codechart import read_key_data
    from ui_theme import ThemeManager
    from virtual_keyboard import VirtualKeyboardView
    from windows_integration import show_guide_without_activation

    warnings, stages = [], []
    old_handler = qInstallMessageHandler(
        lambda kind, context, text: warnings.append(text)
        if kind in (QtWarningMsg, QtCriticalMsg, QtFatalMsg) else None)
    app = backdrop = view = None
    result = dict(status='failed', skipped=False, baseline_established=False,
                  stages=stages, qt_warnings=warnings,
                  display_change_test='simulated font metrics and Qt screen signals; real desktop pixel sampling')

    def flush():
        loop = QEventLoop()
        QTimer.singleShot(160, loop.quit)
        loop.exec_()

    def own_region():
        bounds = wintypes.RECT()
        if not api.GetWindowRect(int(backdrop.winId()), ctypes.byref(bounds)):
            raise OwnedRegionUnavailable('Cannot locate the test backdrop')
        # Refuse capture if another process obscures the test area. This never
        # raises, activates or otherwise manipulates the obstructing window.
        for y in range(bounds.top + 3, bounds.bottom - 3, max(1, (bounds.bottom - bounds.top) // 30)):
            for x in range(bounds.left + 3, bounds.right - 3, max(1, (bounds.right - bounds.left) // 40)):
                hwnd = api.WindowFromPoint(wintypes.POINT(x, y))
                owner = wintypes.DWORD()
                api.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if owner.value != os.getpid():
                    raise OwnedRegionUnavailable('Test region obscured; refusing desktop capture')

    def pink(color):
        return all(abs(channel - expected) < 12 for channel, expected in
                   zip((color.red(), color.green(), color.blue()), BACKGROUND))

    def capture():
        own_region()
        origin = backdrop.mapToGlobal(QPoint())
        pixmap = backdrop.screen().grabWindow(0, origin.x(), origin.y(), backdrop.width(), backdrop.height())
        own_region()
        return origin, pixmap, pixmap.toImage()

    def sample(name, visible=True, minimized=False):
        flush()
        assert not warnings, 'Qt warnings: ' + '; '.join(warnings)
        assert view.isVisible() == visible and view.isMinimized() == minimized, name
        hwnd = int(view.effectiveWinId() or 0)
        if visible:
            assert hwnd and api.IsWindowVisible(hwnd) and bool(api.IsIconic(hwnd)) == minimized, name
        origin, pixmap, image = capture()
        assert not image.isNull(), 'Desktop capture unavailable'
        ratio_x, ratio_y = image.width() / backdrop.width(), image.height() / backdrop.height()
        assert all(pink(image.pixelColor(x, y)) for x, y in (
            (3, 3), (image.width() - 4, 3), (3, image.height() - 4),
            (image.width() - 4, image.height() - 4))), 'No composed test backdrop'
        samples = []
        if visible and not minimized:
            for cap in view.crs.values():
                if not cap.isVisibleTo(view.chart_widget):
                    continue
                board_point = cap.mapTo(view.chart_widget, cap.rect().center())
                viewport_point = view.scroll_area.mapFromScene(QPointF(board_point))
                point = view.scroll_area.viewport().mapToGlobal(viewport_point) - origin
                x, y = round(point.x() * ratio_x), round(point.y() * ratio_y)
                assert 0 <= x < image.width() and 0 <= y < image.height(), 'Guide left test backdrop'
                samples.append(not pink(image.pixelColor(x, y)))
            assert len(samples) >= 50 and sum(samples) / len(samples) >= .95, (
                f'{name}: guide invisible; {sum(samples)} of {len(samples)} keys visible')
        else:
            assert all(pink(image.pixelColor(x, y))
                       for y in range(4, image.height(), 16)
                       for x in range(4, image.width(), 16)), 'Hidden guide still appears'
        stages.append(dict(name=name, visible_keys=sum(samples), sampled_keys=len(samples),
                           width=view.width(), height=view.height(), visible=visible, minimized=minimized))
        if save_images:
            directory = report.parent / (report.stem + '-images')
            directory.mkdir(parents=True, exist_ok=True)
            assert pixmap.save(str(directory / (name + '.png')))

    def drag(start, delta):
        viewport = view.scroll_area.viewport()
        global_start = viewport.mapToGlobal(start)
        for kind, offset, button, buttons in (
                (QEvent.MouseButtonPress, QPoint(), Qt.LeftButton, Qt.LeftButton),
                (QEvent.MouseMove, delta, Qt.NoButton, Qt.LeftButton),
                (QEvent.MouseButtonRelease, delta, Qt.LeftButton, Qt.NoButton)):
            app.sendEvent(viewport, QMouseEvent(kind, QPointF(start + offset),
                          QPointF(global_start + offset), button, buttons, Qt.NoModifier))

    def assert_text_and_board_fit():
        labels = 0
        for cap in view.crs.values():
            if not cap.isVisibleTo(view.chart_widget):
                continue
            for label in (cap.character, cap.codeline):
                bounds = label.contentsRect().adjusted(label.margin(), label.margin(),
                                                       -label.margin(), -label.margin())
                assert bounds.height() >= label.fontMetrics().height(), 'Key text height clipped'
                assert bounds.width() >= label.fontMetrics().horizontalAdvance(label.text()), 'Key text width clipped'
                labels += 1
        mapped = view.scroll_area.transform().mapRect(view.scroll_area.sceneRect())
        viewport = view.scroll_area.viewport().rect()
        assert 0 <= viewport.width() - mapped.width() < 2, 'Compact board width detached from window'
        assert 0 <= viewport.height() - mapped.height() < 2, 'Compact board height detached from window'
        return labels

    def simulate_font_metrics(fonts, factor):
        # This alters only our labels, not Windows DPI or any other application.
        # Emit the real screen object's signal to exercise its current binding,
        # including the binding restored after native-window recreation.
        for label, original in fonts.items():
            font = QFont(original)
            if factor != 1:
                font.setPointSizeF(original.pointSizeF() * factor)
            label.setFont(font)
        screen = view.windowHandle().screen()
        screen.logicalDotsPerInchChanged.emit(screen.logicalDotsPerInch() * factor)

    try:
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        theme = ThemeManager(app, 'dark')
        if app.primaryScreen() is None:
            raise NativeDesktopUnavailable('No screen available; guide test not executed')
        available = app.primaryScreen().availableGeometry()
        if available.width() < 1000 or available.height() < 700:
            raise RuntimeError('Desktop smaller than 1000 x 700; cannot exercise readable resizing')
        backdrop = QWidget()
        backdrop.setWindowTitle('Morse native guide test backdrop')
        backdrop.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        backdrop.setStyleSheet('background: rgb(229, 16, 160);')
        backdrop.setGeometry(available.adjusted(12, 12, -12, -12))
        show_guide_without_activation(backdrop)
        flush()
        try:
            _origin, _pixmap, baseline = capture()
        except OwnedRegionUnavailable as error:
            # No guide exists yet: CI cannot establish the independent desktop
            # baseline. The same exception after this point remains a failure.
            raise NativeDesktopUnavailable('Backdrop baseline unavailable; guide test not executed: '
                                           + str(error)) from error
        if baseline.isNull() or not all(pink(baseline.pixelColor(x, y))
                for y in range(4, baseline.height(), 16) for x in range(4, baseline.width(), 16)):
            raise NativeDesktopUnavailable('Solid backdrop could not be sampled; guide test not executed')
        result['baseline_established'] = True
        layout = json.loads((ROOT / 'user_data/layouts.json').read_text(encoding='utf-8-sig'))['layouts']['desktop']
        labels = read_key_data(ROOT / 'MorseCodeGUI.py')
        for item in layout['items']:
            item['label'] = item.get('label', labels.get(item['action'], {}).get('label', item['action']))
        view = VirtualKeyboardView(layout, dict(show_mouse=False, guide_auto_fit=True, upperchars=True))
        view.resize(min(900, backdrop.width() - 100), min(600, backdrop.height() - 100))
        view.move(backdrop.pos() + QPoint(35, 35))
        show_guide_without_activation(view)
        sample('full')
        original_size = view.size()
        key = next(iter(view.crs.values()))
        result['display_environment'] = dict(
            automatic_high_dpi_scaling=app.testAttribute(Qt.AA_EnableHighDpiScaling),
            win32_awareness=api.GetAwarenessFromDpiAwarenessContext(api.GetThreadDpiAwarenessContext()),
            window_dpi=api.GetDpiForWindow(int(view.effectiveWinId())),
            screens=[dict(name=screen.name(), geometry=screen.geometry().getRect(),
                          logical_dpi=screen.logicalDotsPerInch(), device_pixel_ratio=screen.devicePixelRatio())
                     for screen in app.screens()],
            label_font_dpi=key.character.fontMetrics().fontDpi(),
            label_paint_device_dpi=key.character.logicalDpiY(),
            label_device_font_dpi=QFontMetrics(key.character.font(), key.character).fontDpi(),
            physical_monitor_changes_tested=False)
        QTest.mouseClick(view.compact_checkbox, Qt.LeftButton)
        assert view.isCompactMode()
        sample('top-checkbox-compact')
        maximum = min(1.15, (backdrop.width() - 150) / view.scroll_area.sceneRect().width(),
                      (backdrop.height() - 150) / view.scroll_area.sceneRect().height())
        minimum = max(view._minimumCompactScale(), maximum * .8)
        assert maximum > minimum, 'Desktop cannot exercise resizing at readable scale'
        view.setCompactScale(maximum)
        sample('larger')
        large_size = view.size()
        view.setCompactScale(minimum)
        assert view.width() < large_size.width()
        sample('smaller')
        old_size = view.size()
        drag(QPoint(view.width() - 2, view.height() // 2), QPoint(40, 0))
        assert view.width() > old_size.width()
        sample('edge-resize')
        old_size = view.size()
        drag(QPoint(view.width() - 2, view.height() - 2), QPoint(25, 15))
        assert view.width() > old_size.width()
        sample('corner-resize')
        old_position, old_size = view.pos(), view.size()
        drag(view.scroll_area.viewport().rect().center(), QPoint(16, 12))
        assert view.pos() != old_position and view.size() == old_size
        sample('drag-move')
        for index, compact in enumerate((False, True, False)):
            view.setCompactMode(compact)
            assert not sip.isdeleted(key)
            if not compact:
                assert view.size() == original_size
            sample('mode-' + str(index))
        view.hide()
        view.setCompactMode(True)
        sample('hidden-mode-change', visible=False)
        show_guide_without_activation(view)
        sample('hidden-restored')
        view.showMinimized()
        flush()
        assert view.isMinimized() and api.IsIconic(int(view.winId()))
        view.setCompactMode(False)
        sample('minimized-mode-change', minimized=True)
        show_guide_without_activation(view)
        sample('minimized-restored')

        # Keep all native transition regressions above. These extra stages
        # simulate changed font metrics while checking actual desktop pixels;
        # they are not a claim that Windows monitor settings were changed.
        view.setCompactMode(True)
        view.setCompactScale(min(view.compactScale(),
            (backdrop.width() - 200) / (view.scroll_area.sceneRect().width() * 1.6),
            (backdrop.height() - 200) / (view.scroll_area.sceneRect().height() * 1.6)))
        flush()
        fonts = {label: QFont(label.font()) for cap in view.crs.values()
                 for label in (cap.character, cap.codeline)}
        initial_scene = view.scroll_area.sceneRect()
        initial_size = view.size()
        requested_scale = view.compactScale()
        for factor, name in ((1.4, 'simulated-dpi-larger'), (1, 'simulated-dpi-restored')):
            simulate_font_metrics(fonts, factor)
            sample(name)
            stages[-1].update(simulated_display_change=True, labels_fitting=assert_text_and_board_fit())
            assert view.compactScale() == requested_scale, 'DPI refresh changed the user scale preference'
            if factor > 1:
                # At low DPI the minimum key height can still accommodate the
                # larger text. Width alone may grow, which is correct too.
                current_scene = view.scroll_area.sceneRect()
                assert (current_scene.width() > initial_scene.width() or
                        current_scene.height() > initial_scene.height()), 'DPI metrics stayed cached'
                assert (view.width() > initial_size.width() or
                        view.height() > initial_size.height()), 'Larger font metrics did not resize compact window'
            else:
                assert view.scroll_area.sceneRect() == initial_scene and view.size() == initial_size, 'Restored metrics stayed enlarged'
        view.hide()
        simulate_font_metrics(fonts, 1.4)
        sample('simulated-dpi-hidden', visible=False)
        stages[-1]['simulated_display_change'] = True
        show_guide_without_activation(view)
        sample('simulated-dpi-hidden-restored')
        stages[-1].update(simulated_display_change=True, labels_fitting=assert_text_and_board_fit())
        assert view.compactScale() == requested_scale
        result['status'] = 'passed'
    except NativeDesktopUnavailable as error:
        result.update(status='unavailable', skipped=True, reason=str(error))
    except Exception as error:
        result['reason'] = str(error)
    finally:
        for widget in (view, backdrop):
            if widget is not None and not sip.isdeleted(widget):
                widget.hide()
                widget.deleteLater()
        if app is not None:
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
        qInstallMessageHandler(old_handler)
        if warnings:
            result.update(status='failed', skipped=False, reason='Qt emitted warnings')
    return result, {'passed': 0, 'failed': 1, 'unavailable': 2}[result['status']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path, help='JSON output inside build/')
    parser.add_argument('--save-images', action='store_true', help='Save only the owned test area beside the report')
    parser.add_argument('--allow-unavailable', action='store_true',
                        help='Allow unavailable desktop/backdrop only; still report unavailable, never passed')
    args = parser.parse_args()
    report = args.report.resolve()
    if not report.is_relative_to(ROOT / 'build'):
        parser.error('--report must be inside this project\'s build directory')
    try:
        result, code = check_native(report, args.save_images)
    except Exception as error:
        result, code = dict(status='failed', skipped=False, reason=str(error)), 1
    if args.allow_unavailable and result['status'] == 'unavailable':
        code = 0
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
