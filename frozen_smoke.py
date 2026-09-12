"""Noninteractive installation check; no hooks, hotkeys, or synthetic input."""

import json
import sys
from pathlib import Path
import traceback

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication

from app_paths import prediction_database, source_resource, user_data_dir


def verify_installation(window, report_path):
    def run():
        result = {'ok': False}
        try:
            assert window.config['theme'] == 'system', 'Fresh installs must follow the system theme'
            window._start_hidden = True
            window.init()
            view = window.codeslayoutview
            assert len(view.crs) == 137, 'Missing guide actions'
            assert window.listenerThread is None, 'Smoke check must not install input hooks'
            assert not window._desktop_integration_started
            assert not view.isVisible() and not window.isVisible()
            assert window.onOffAction.isCheckable() and not window.onOffAction.isChecked()
            assert not window.windowIcon().isNull()
            assert window.typestate.getpredictions(), 'Prediction database failed to load'
            database = prediction_database()
            assert database.parent == user_data_dir().resolve()
            view.setAttribute(Qt.WA_DontShowOnScreen)
            window.toggleGuideVisibility()
            assert view.isVisible()
            window.toggleGuideVisibility()
            assert not view.isVisible()
            result.update(ok=True, frozen=bool(getattr(sys, 'frozen', False)),
                          version=source_resource('version').read_text().strip(),
                          theme=window.config['theme'], guide_actions=len(view.crs),
                          database=str(database), hotkey=window.config['guide_hotkey'],
                          startup_hidden=True, input_hooks=False)
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
