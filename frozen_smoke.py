"""Noninteractive installation check; no hooks, hotkeys, or synthetic input."""

import json
import importlib.util
from math import ceil
import sys
from pathlib import Path
import traceback

from PyQt5.QtCore import QPointF, QRect, QTimer, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

from app_paths import source_resource, user_data_dir


def _assert_navigation_gap_transparent(view, image):
    # The empty cell above Left and left of Up stays well clear of key edges.
    # An outer corner can contain a rounded key's antialiasing after scaling.
    board = view.scroll_area.board
    left, up = (view.keystroke_crs_map[key] for key in ('LEFTARROW', 'UPARROW'))
    left_center = left.mapTo(board, left.rect().center())
    up_center = up.mapTo(board, up.rect().center())
    scene_point = view.scroll_area.proxy.mapToScene(QPointF(left_center.x(), up_center.y()))
    point = view.scroll_area.viewport().mapTo(view, view.scroll_area.mapFromScene(scene_point))
    assert image.rect().contains(point), 'Navigation gap is outside the rendered guide'
    assert image.pixelColor(point).alpha() == 0, 'Guide gaps are not transparent'
    return point


def verify_interface_features(window):
    """Render the real compact guide while its native window stays hidden."""
    view = window.codeslayoutview
    assert not view.isVisible() and not window.isVisible()
    assert not view.isCompactMode(), 'Fresh installs must start in full view'
    preset = window.hotkeyPresetComboBox
    previous_index = preset.currentIndex()
    previous_sequence = window.hotkeyEdit.keySequence()
    previous_enabled = window.hotkeyEnabledCheck.isChecked()
    saved_hotkey = window.config['guide_hotkey']
    try:
        index = preset.findData('F22')
        assert index >= 0, 'F22 is missing from shortcut presets'
        window.hotkeyEnabledCheck.setChecked(True)
        preset.setCurrentIndex(index)
        assert window.selectedGuideHotkey() == 'F22'
        assert window.config['guide_hotkey'] == saved_hotkey, 'Selecting a preset must not register it'
    finally:
        window.hotkeyEnabledCheck.setChecked(previous_enabled)
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
        _assert_navigation_gap_transparent(view, image)
        cap = view.crs['12']  # A visible key must actually paint into the image.
        point = cap.mapTo(view.scroll_area.board, cap.rect().center())
        scene_point = proxy.mapToScene(QPointF(point))
        point = view.scroll_area.viewport().mapTo(view, view.scroll_area.mapFromScene(scene_point))
        assert image.rect().contains(point) and image.pixelColor(point).alpha() > 0
        metrics = {'size': [view.width(), view.height()],
                   'board': [board.width(), board.height()], 'transparent_gap': True,
                   'painted_key': True, 'hotkey_preset': 'F22'}
        resize_sizes = []
        for requested_scale in (0.8, 1.0):
            if requested_scale == 1.0:
                view.resetCompactScale()
                assert view.compactScale() == 1.0, 'Reset did not restore the default compact scale'
            else:
                view.setCompactScale(requested_scale)
            scale = view.compactScale()
            saved = json.loads(Path(window.configManager.config_file).read_text(encoding='utf-8'))
            assert saved['guide_compact_scale'] == scale, 'Compact scale was not saved'
            assert window.config['guide_compact_scale'] == scale
            image = QImage(view.size(), QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            view.render(image)
            bounds = view.scroll_area.sceneRect()
            available = QApplication.desktop().availableGeometry(view)
            visible_scale = min(scale, available.width() / bounds.width(),
                                available.height() / bounds.height())
            assert abs(view.width() - ceil(bounds.width() * visible_scale)) <= 1
            assert abs(view.height() - ceil(bounds.height() * visible_scale)) <= 1
            board = view.scroll_area.mapFromScene(bounds).boundingRect()
            assert abs(board.width() - view.width()) <= 2
            assert abs(board.height() - view.height()) <= 2
            _assert_navigation_gap_transparent(view, image)
            assert not view.isVisible(), 'Resizing must not reveal the hidden guide'
            resize_sizes.append([view.width(), view.height()])
            if requested_scale != 1.0:
                metrics['resized_scale'] = scale
                view.setCompactMode(False)
                assert view.geometry() == geometry
                view.setCompactMode(True)
                assert view.compactScale() == scale, 'Reopening compact mode lost its scale'
        metrics.update(resize_sizes=resize_sizes, reset_scale=view.compactScale(), scale_saved=True)
        layer_geometry = QRect(view.geometry())
        layer_handle = int(view.winId())
        layer_config = Path(window.configManager.config_file).read_bytes()
        assert window.config['pinyin_layer_enabled'] is True
        assert window.config['pinyin_layer_key'] == 'F22'
        assert window.config['pinyin_layer_mode'] == 'toggle'
        assert window.pinyinToggleRadio.text() == '双击切换'
        assert not window.pinyinHoldRadio.isHidden() and not window.pinyinToggleRadio.isHidden()
        assert not window.imeSyncCheck.isChecked() and not window.ime_sync.enabled
        assert window.settings_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert window.selectedPinyinMode() == 'toggle'
        window.pinyinHoldRadio.setChecked(True)
        assert window.selectedPinyinMode() == 'hold'
        window.pinyinToggleRadio.setChecked(True)
        view.setPinyinMode(True, window._pinyin_layout)
        try:
            assert view.isPinyinMode() and len(view.crs) == 142
            for code, text in (('222', 'a'), ('1111', 'zh'), ('221', 'ang')):
                assert view.crs[code].item['pinyin_text'] == text
            assert view.keystroke_crs_map['ONE'].character.text() == '1'
            assert len([cap for cap in view.crs.values() if 'pinyin_symbol' in cap.item]) == 26
            image = QImage(view.size(), QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            view.render(image)
            assert not view.isVisible(), 'Switching layer must preserve hidden state'
            assert view.geometry() == layer_geometry and int(view.winId()) == layer_handle
            assert Path(window.configManager.config_file).read_bytes() == layer_config
            metrics['pinyin_layer'] = {'actions': len(view.crs), 'key': 'F22',
                                       'modes': ['hold', 'toggle'], 'geometry_preserved': True}
        finally:
            view.setPinyinMode(False)
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
            assert len(view.crs) == 130, 'Missing guide actions'
            assert set(window.layoutManager.layouts) == {'desktop'}, 'Retired layout pages remain'
            for code, action in (('21121', 'FSLASH'), ('1112112', 'DOLLAR'),
                                 ('1111111', 'BACKTICK'), ('1221121', 'DELETE')):
                assert view.crs[code].item['action'] == action, 'Guide profile does not match dispatch'
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
            assert not (data_directory / 'abbreviations_en.txt').exists(), 'Retired abbreviation resource was created'
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
