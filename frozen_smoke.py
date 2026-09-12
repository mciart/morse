"""Noninteractive installation check; no hooks, hotkeys, or synthetic input."""

import json
import importlib.util
import sys
from pathlib import Path
import traceback

from PyQt5.QtCore import QPointF, QRect, QTimer, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

from app_paths import source_resource, user_data_dir


def verify_interface_features(window):
    """Render the real compact guide while its native window stays hidden."""
    view = window.codeslayoutview
    assert not view.isVisible() and not window.isVisible()
    assert not view.isCompactMode(), 'Fresh installs must start in full view'
    preset = window.hotkeyPresetComboBox
    previous_index = preset.currentIndex()
    previous_sequence = window.hotkeyEdit.keySequence()
    saved_hotkey = window.config['guide_hotkey']
    try:
        index = preset.findData('F22')
        assert index >= 0, 'F22 is missing from shortcut presets'
        preset.setCurrentIndex(index)
        assert window.selectedGuideHotkey() == 'F22'
        assert window.config['guide_hotkey'] == saved_hotkey, 'Selecting a preset must not register it'
    finally:
        preset.setCurrentIndex(previous_index)
        window.hotkeyEdit.setKeySequence(previous_sequence)

    geometry = QRect(view.geometry())
    caps = dict(view.crs)
    proxy = view.scroll_area.proxy
    view.setAttribute(Qt.WA_DontShowOnScreen)
    try:
        view.setCompactMode(True)
        image = QImage(view.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        view.render(image)
        assert not view.isVisible(), 'Compact rendering must remain hidden'
        assert view.windowFlags() & Qt.FramelessWindowHint
        assert view.windowFlags() & Qt.WindowStaysOnTopHint
        assert view.testAttribute(Qt.WA_TranslucentBackground)
        assert view.scroll_area.geometry() == view.rect(), 'Compact guide has outer padding'
        board = view.scroll_area.mapFromScene(view.scroll_area.sceneRect()).boundingRect()
        assert abs(board.width() - view.width()) <= 2
        assert abs(board.height() - view.height()) <= 2
        assert view.height() < geometry.height(), 'Compact guide did not shrink'
        assert all(widget.isHidden() for widget in
                   (view.header_widget, view.input_feedback, view.status_bar))
        assert image.pixelColor(0, 0).alpha() == 0, 'Guide gaps are not transparent'
        cap = view.crs['12']  # A visible key must actually paint into the image.
        point = cap.mapTo(view.scroll_area.board, cap.rect().center())
        scene_point = proxy.mapToScene(QPointF(point))
        point = view.scroll_area.viewport().mapTo(view, view.scroll_area.mapFromScene(scene_point))
        assert image.rect().contains(point) and image.pixelColor(point).alpha() > 0
        metrics = {'size': [view.width(), view.height()],
                   'board': [board.width(), board.height()], 'transparent_gap': True,
                   'painted_key': True, 'hotkey_preset': 'F22'}
    finally:
        view.setCompactMode(False)
    assert view.geometry() == geometry, 'Full guide geometry was not restored'
    assert not view.isVisible() and not window.isVisible()
    assert view.scroll_area.proxy is proxy and view.crs == caps
    assert window.listenerThread is None and not window._desktop_integration_started
    metrics['restored'] = True
    return metrics


def verify_installation(window, report_path):
    def run():
        result = {'ok': False}
        try:
            assert window.config['theme'] == 'system', 'Fresh installs must follow the system theme'
            window._start_hidden = True
            window.init()
            view = window.codeslayoutview
            assert len(view.crs) == 129, 'Missing guide actions'
            assert window.listenerThread is None, 'Smoke check must not install input hooks'
            assert not window._desktop_integration_started
            assert not view.isVisible() and not window.isVisible()
            assert window.onOffAction.isCheckable() and not window.onOffAction.isChecked()
            assert not window.windowIcon().isNull()
            data_directory = user_data_dir().resolve()
            assert (data_directory / 'config.json').is_file()
            assert (data_directory / 'layouts.json').is_file()
            assert 'pressagio' not in sys.modules, 'Removed prediction engine was loaded'
            assert not (data_directory / 'morsewriter.sqlite').exists(), 'Fresh installs must not create a word database'
            if getattr(sys, 'frozen', False):
                assert importlib.util.find_spec('pressagio') is None, 'Removed engine is still bundled'
                assert not source_resource('defaults', 'morsewriter.sqlite').exists()
                assert not source_resource('res', 'morsewriter_pressagio.ini').exists()
            compact = verify_interface_features(window)
            view.setAttribute(Qt.WA_DontShowOnScreen)
            window.toggleGuideVisibility()
            assert view.isVisible()
            window.toggleGuideVisibility()
            assert not view.isVisible()
            result.update(ok=True, frozen=bool(getattr(sys, 'frozen', False)),
                          version=source_resource('version').read_text().strip(),
                          theme=window.config['theme'], guide_actions=len(view.crs),
                          user_data=str(data_directory), hotkey=window.config['guide_hotkey'],
                          startup_hidden=True, input_hooks=False, compact_guide=compact)
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            window.shutdown()
            window.trayIcon.hide()
            report = Path(report_path)
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            QApplication.instance().exit(0 if result['ok'] else 1)

    QTimer.singleShot(0, run)
