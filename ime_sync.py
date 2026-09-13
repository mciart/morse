"""Bounded IME polling and verified writes outside the GUI/audio thread."""

import logging
import os
import threading
from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from windows_ime import NativeImeBackend, ImeSetResult


class ImeSynchronizer(QObject):
    stateChanged = pyqtSignal(object)
    requestFinished = pyqtSignal(int, object)
    _observed = pyqtSignal(int, object)
    _finished = pyqtSignal(int, int, object)

    def __init__(self, parent=None, *, backend_factory=NativeImeBackend, target_factory=None, interval=.15):
        super().__init__(parent)
        self._factory = backend_factory
        self._target_factory = target_factory or NativeImeBackend.capture_target
        self._interval = interval
        self._epoch = 0
        self._serial = 0
        self._worker = None
        self._stop = None
        self._wake = None
        self._lock = threading.Lock()
        self._command = None
        self.latest = None
        self.enabled = False
        self._failed = False
        self._observed.connect(self._receive_state)
        self._finished.connect(self._receive_result)

    def start(self):
        if self.enabled:
            return
        self.enabled = True
        self._failed = False
        self._epoch += 1
        self.latest = None
        self._stop, self._wake = threading.Event(), threading.Event()
        self._worker = threading.Thread(target=self._run,
            args=(self._epoch, self._stop, self._wake), daemon=True, name='MorseWriter-IME')
        self._worker.start()

    def stop(self):
        self.enabled = False
        self._epoch += 1
        with self._lock:
            self._command = None
        if self._stop is not None:
            self._stop.set()
            self._wake.set()
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.join(.4)
        self.latest = None

    def request(self, chinese, expected=None):
        if not self.enabled:
            return None
        self._serial += 1
        if self._failed:
            epoch, serial = self._epoch, self._serial
            QTimer.singleShot(0, lambda: self._receive_result(
                epoch, serial, ImeSetResult(False, None, 'backend_error'))
                if serial == self._serial else None)
            return serial
        if expected is None:
            try:
                expected = self._target_factory()
            except Exception:
                epoch, serial = self._epoch, self._serial
                QTimer.singleShot(0, lambda: self._receive_result(
                    epoch, serial, ImeSetResult(False, None, 'target_unavailable'))
                    if serial == self._serial else None)
                return serial
        with self._lock:
            self._command = (self._serial, bool(chinese), expected)
        self._wake.set()
        return self._serial

    @staticmethod
    def target_matches(state):
        return state is not None and NativeImeBackend.target_matches(state)

    def _receive_state(self, epoch, state):
        if self.enabled and epoch == self._epoch:
            changed = state != self.latest
            self.latest = state
            if changed:
                self.stateChanged.emit(state)

    def _receive_result(self, epoch, serial, result):
        if self.enabled and epoch == self._epoch:
            if result.reason == 'backend_error':
                self._failed = True
                self.latest = None
                self.stateChanged.emit(None)
                self.requestFinished.emit(self._serial, result)
                return
            if serial != self._serial:
                return
            self.latest = result.state
            self.requestFinished.emit(serial, result)

    def _run(self, epoch, stop, wake):
        backend = None
        try:
            backend = self._factory()
            while not stop.is_set():
                wake.clear()
                with self._lock:
                    command = self._command
                    if command is not None and epoch == self._epoch:
                        self._command = None
                    else:
                        command = None
                if command is not None:
                    serial, chinese, expected = command
                    state = expected if expected is not None else backend.snapshot()
                    if stop.is_set() or epoch != self._epoch:
                        break
                    result = (ImeSetResult(False, state, 'own_window')
                              if state.process_id == os.getpid()
                              else backend.set_chinese(state, chinese))
                    if not stop.is_set():
                        self._finished.emit(epoch, serial, result)
                else:
                    state = backend.snapshot()
                    if not stop.is_set():
                        self._observed.emit(epoch, state)
                wake.wait(self._interval)
        except Exception:
            # Native adapters normally return a reason. An unexpected backend
            # failure must still leave the GUI responsive and fail closed.
            if not stop.is_set():
                self._finished.emit(epoch, self._serial,
                                    ImeSetResult(False, None, 'backend_error'))
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    logging.exception('Unable to close the IME backend')
