"""IME worker isolation and stale-result rejection without native input APIs."""

from dataclasses import replace
import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QEvent, QTimer, Qt
from PyQt5.QtWidgets import QApplication

from ime_sync import ImeSynchronizer
from windows_ime import ImeState, ImeSetResult


ENGLISH = ImeState(foreground=101, focus=102, thread_id=103, process_id=104,
                   layout=0x08040804, ime_window=105, is_pinyin=True,
                   chinese=False, open_status=True, conversion=0)
CHINESE = replace(ENGLISH, chinese=True, conversion=1)


class FakeBackend:
    def __init__(self, state=ENGLISH, snapshot=None, set_chinese=None, close=None):
        self.state = state
        self.on_snapshot = snapshot
        self.on_set = set_chinese
        self.on_close = close
        self.calls = []
        self.closed = threading.Event()
        self.created_thread = threading.get_ident()

    def snapshot(self):
        self.calls.append(('snapshot', threading.get_ident()))
        return self.on_snapshot() if self.on_snapshot else self.state

    def set_chinese(self, expected, chinese):
        self.calls.append(('set', threading.get_ident(), expected, chinese))
        if self.on_set:
            return self.on_set(expected, chinese)
        self.state = replace(expected, chinese=chinese, conversion=int(chinese))
        return ImeSetResult(True, self.state)

    def close(self):
        self.calls.append(('close', threading.get_ident()))
        try:
            if self.on_close:
                self.on_close()
        finally:
            self.closed.set()


class ImeSynchronizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.gui_thread = threading.get_ident()
        self.syncs = []
        self.backends = []
        self.gates = []

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        for sync in self.syncs:
            sync.stop()
        for backend in self.backends:
            self.assertTrue(backend.closed.wait(2), 'worker failed to close its backend')
        for sync in self.syncs:
            sync.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def gate(self):
        gate = threading.Event()
        self.gates.append(gate)
        return gate

    def wait_gate(self, gate):
        if not gate.wait(2):
            raise RuntimeError('test gate timed out')

    def spin_until(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            threading.Event().wait(.002)
        self.app.processEvents()
        self.assertTrue(predicate(), 'Qt event loop condition timed out')

    def make_sync(self, *, factory=None, target_factory=None, interval=.01, **backend_options):
        def default_factory():
            backend = FakeBackend(**backend_options)
            self.backends.append(backend)
            return backend
        sync = ImeSynchronizer(backend_factory=factory or default_factory,
                               target_factory=target_factory or (lambda: ENGLISH), interval=interval)
        self.syncs.append(sync)
        return sync

    def test_backend_constructs_polls_writes_and_closes_on_its_own_worker(self):
        sync = self.make_sync()
        states, results, receiver_threads = [], [], []
        sync.stateChanged.connect(lambda state: (states.append(state),
                                                 receiver_threads.append(threading.get_ident())))
        sync.requestFinished.connect(lambda serial, result: (results.append((serial, result)),
                                                             receiver_threads.append(threading.get_ident())))
        sync.start()
        self.spin_until(lambda: bool(states))
        serial = sync.request(True, ENGLISH)
        self.spin_until(lambda: bool(results))
        sync.stop()
        backend = self.backends[0]
        self.assertTrue(backend.closed.wait(2))
        self.assertNotEqual(backend.created_thread, self.gui_thread)
        self.assertEqual({call[1] for call in backend.calls}, {backend.created_thread})
        self.assertEqual(set(receiver_threads), {self.gui_thread})
        self.assertEqual(results, [(serial, ImeSetResult(True, CHINESE))])
        self.assertIsNone(sync.latest)

    def test_stalled_native_write_keeps_gui_timers_and_request_return_responsive(self):
        entered, release = threading.Event(), self.gate()
        def write(expected, chinese):
            entered.set()
            self.wait_gate(release)
            return ImeSetResult(True, CHINESE)
        sync = self.make_sync(set_chinese=write)
        sync.start()
        self.spin_until(lambda: sync.latest is not None)
        results, timers = [], []
        sync.requestFinished.connect(lambda serial, result: results.append((serial, result)))
        serial = sync.request(True, ENGLISH)
        self.assertTrue(entered.wait(2))
        QTimer.singleShot(0, lambda: timers.append('GUI alive'))
        self.spin_until(lambda: bool(timers))
        self.assertEqual(results, [])
        release.set()
        self.spin_until(lambda: bool(results))
        self.assertEqual(results[0][0], serial)

    def test_latest_queued_request_runs_before_poll_and_supersedes_earlier_request(self):
        factory_entered, release_factory = threading.Event(), self.gate()
        def factory():
            factory_entered.set()
            self.wait_gate(release_factory)
            backend = FakeBackend()
            self.backends.append(backend)
            return backend
        sync = self.make_sync(factory=factory, interval=.5)
        results = []
        sync.requestFinished.connect(lambda serial, result: results.append((serial, result)))
        sync.start()
        self.assertTrue(factory_entered.wait(2))
        first = sync.request(True, ENGLISH)
        second = sync.request(False, ENGLISH)
        release_factory.set()
        self.spin_until(lambda: bool(results))
        backend = self.backends[0]
        self.assertGreater(second, first)
        self.assertEqual(backend.calls[0], ('set', backend.created_thread, ENGLISH, False))
        self.assertEqual([call[2:] for call in backend.calls if call[0] == 'set'], [(ENGLISH, False)])
        self.assertEqual(results, [(second, ImeSetResult(True, ENGLISH))])

    def test_inflight_old_result_is_filtered_when_newer_request_is_pending(self):
        first_entered, second_entered = threading.Event(), threading.Event()
        first_release, second_release = self.gate(), self.gate()
        writes = []
        def write(expected, chinese):
            writes.append(chinese)
            entered, release = ((first_entered, first_release) if len(writes) == 1
                                else (second_entered, second_release))
            entered.set()
            self.wait_gate(release)
            return ImeSetResult(True, CHINESE if chinese else ENGLISH)
        sync = self.make_sync(set_chinese=write)
        sync.start()
        self.spin_until(lambda: sync.latest is not None)
        results = []
        sync.requestFinished.connect(lambda serial, result: results.append((serial, result)))
        first = sync.request(True, ENGLISH)
        self.assertTrue(first_entered.wait(2))
        second = sync.request(False, ENGLISH)
        first_release.set()
        self.assertTrue(second_entered.wait(2))
        self.app.processEvents()
        self.assertEqual(results, [])
        self.assertEqual(sync.latest, ENGLISH)
        second_release.set()
        self.spin_until(lambda: bool(results))
        self.assertGreater(second, first)
        self.assertEqual(results, [(second, ImeSetResult(True, ENGLISH))])

    def test_request_without_expected_state_captures_gui_target_before_worker_write(self):
        target_threads = []
        target = replace(ENGLISH, foreground=201, focus=202)
        def capture():
            target_threads.append(threading.get_ident())
            return target
        sync = self.make_sync(interval=.5, target_factory=capture)
        sync.start()
        self.spin_until(lambda: sync.latest is not None)
        backend = self.backends[0]
        backend.calls.clear()
        results = []
        sync.requestFinished.connect(lambda serial, result: results.append(result))
        sync.request(True)
        self.spin_until(lambda: bool(results))
        self.assertEqual(target_threads, [self.gui_thread])
        self.assertEqual(backend.calls[0][0], 'set')
        self.assertEqual(backend.calls[0][2:], (target, True))

    def test_expected_target_bypasses_capture_and_own_window_is_never_written(self):
        def capture():
            raise AssertionError('explicit target must not be replaced')
        sync = self.make_sync(target_factory=capture)
        sync.start()
        self.spin_until(lambda: sync.latest is not None)
        results = []
        sync.requestFinished.connect(lambda serial, result: results.append((serial, result)))
        own_window = replace(ENGLISH, process_id=os.getpid())
        serial = sync.request(True, own_window)
        self.spin_until(lambda: bool(results))
        self.assertEqual(results, [(serial, ImeSetResult(False, own_window, 'own_window'))])
        self.assertFalse(any(call[0] == 'set' for call in self.backends[0].calls))

    def test_stop_restart_discards_queued_old_epoch_state_and_result(self):
        observed, finished = threading.Event(), threading.Event()
        states, results = [], []
        def factory():
            backend = FakeBackend(state=ENGLISH if not self.backends else CHINESE)
            self.backends.append(backend)
            return backend
        sync = self.make_sync(factory=factory, interval=.5)
        sync._observed.connect(lambda *_: observed.set(), Qt.DirectConnection)
        sync._finished.connect(lambda *_: finished.set(), Qt.DirectConnection)
        sync.stateChanged.connect(states.append)
        sync.requestFinished.connect(lambda serial, result: results.append(result))
        sync.start()
        self.assertTrue(observed.wait(2))  # Queued to GUI; deliberately not delivered yet.
        sync.request(False, ENGLISH)
        self.assertTrue(finished.wait(2))
        first_epoch = sync._epoch
        sync.stop()
        self.assertIsNone(sync.request(True, ENGLISH))
        sync.start()
        self.assertGreater(sync._epoch, first_epoch)
        self.spin_until(lambda: sync.latest == CHINESE)
        self.assertEqual(states, [CHINESE])
        self.assertEqual(results, [])
        self.assertTrue(self.backends[0].closed.is_set())
        self.assertEqual(self.backends[0].calls[-1][1], self.backends[0].created_thread)

    def test_poll_emits_only_changed_states(self):
        sync = self.make_sync()
        states = []
        sync.stateChanged.connect(states.append)
        sync.start()
        self.spin_until(lambda: len(self.backends[0].calls) >= 3)
        self.assertEqual(states, [ENGLISH])
        self.backends[0].state = CHINESE
        self.spin_until(lambda: len(states) == 2)
        self.assertEqual(states, [ENGLISH, CHINESE])

    def test_restart_during_old_native_read_does_not_reuse_or_publish_old_worker(self):
        entered, release = threading.Event(), self.gate()
        def factory():
            if not self.backends:
                def snapshot():
                    entered.set()
                    self.wait_gate(release)
                    return ENGLISH
                backend = FakeBackend(snapshot=snapshot)
            else:
                backend = FakeBackend(state=CHINESE)
            self.backends.append(backend)
            return backend
        sync = self.make_sync(factory=factory)
        states = []
        sync.stateChanged.connect(states.append)
        sync.start()
        self.assertTrue(entered.wait(2))
        old_worker = sync._worker
        sync.stop()  # Its bounded join returns although the fake native read is blocked.
        self.assertTrue(old_worker.is_alive())
        self.assertFalse(release.is_set())
        sync.start()
        self.spin_until(lambda: sync.latest == CHINESE)
        new_worker = sync._worker
        self.assertIsNot(new_worker, old_worker)
        release.set()
        self.assertTrue(self.backends[0].closed.wait(2))
        self.app.processEvents()
        self.assertEqual(states, [CHINESE])
        self.assertEqual(sync.latest, CHINESE)
        self.assertTrue(new_worker.is_alive())
        self.assertEqual(self.backends[0].calls[-1][1], self.backends[0].created_thread)

    def test_backend_factory_exception_reports_failure_without_native_calls(self):
        thread_ids = []
        def factory():
            thread_ids.append(threading.get_ident())
            raise OSError('fake native initialization failed')
        sync = self.make_sync(factory=factory)
        results = []
        sync.requestFinished.connect(lambda serial, result: results.append((serial, result)))
        sync.start()
        self.spin_until(lambda: bool(results))
        self.assertEqual(results, [(0, ImeSetResult(False, None, 'backend_error'))])
        self.assertNotEqual(thread_ids[0], self.gui_thread)
        self.assertIsNone(sync.latest)

    def test_snapshot_exception_reports_failure_and_closes_backend_on_worker(self):
        def snapshot():
            raise OSError('fake native snapshot failed')
        sync = self.make_sync(snapshot=snapshot)
        results = []
        sync.requestFinished.connect(lambda serial, result: results.append(result))
        sync.start()
        self.spin_until(lambda: bool(results))
        self.assertEqual(results, [ImeSetResult(False, None, 'backend_error')])
        backend = self.backends[0]
        self.assertTrue(backend.closed.wait(2))
        self.assertEqual([call[0] for call in backend.calls], ['snapshot', 'close'])
        self.assertEqual({call[1] for call in backend.calls}, {backend.created_thread})

    def test_write_exception_finishes_matching_request_as_failure(self):
        def write(expected, chinese):
            raise OSError('fake native write failed')
        sync = self.make_sync(set_chinese=write)
        sync.start()
        self.spin_until(lambda: sync.latest is not None)
        results = []
        sync.requestFinished.connect(lambda serial, result: results.append((serial, result)))
        serial = sync.request(True, ENGLISH)
        self.spin_until(lambda: bool(results))
        self.assertEqual(results, [(serial, ImeSetResult(False, None, 'backend_error'))])
        self.assertTrue(self.backends[0].closed.wait(2))
        self.assertEqual([call[0] for call in self.backends[0].calls].count('set'), 1)

    def test_request_after_fatal_worker_failure_reports_asynchronously(self):
        def factory():
            raise OSError('fake native initialization failed')
        sync = self.make_sync(factory=factory)
        results = []
        sync.requestFinished.connect(lambda serial, result: results.append((serial, result)))
        sync.start()
        self.spin_until(lambda: bool(results))
        results.clear()
        serial = sync.request(True, ENGLISH)
        self.assertEqual(results, [])  # Main must install its pending serial before callback.
        self.spin_until(lambda: bool(results))
        self.assertEqual(results, [(serial, ImeSetResult(False, None, 'backend_error'))])

    def test_request_before_queued_fatal_signal_delivery_cannot_wait_forever(self):
        emitted = threading.Event()
        def factory():
            raise OSError('fake native initialization failed')
        sync = self.make_sync(factory=factory)
        results = []
        sync._finished.connect(lambda *_: emitted.set(), Qt.DirectConnection)
        sync.requestFinished.connect(lambda serial, result: results.append((serial, result)))
        sync.start()
        self.assertTrue(emitted.wait(2))
        serial = sync.request(True, ENGLISH)
        self.assertEqual(results, [])
        self.spin_until(lambda: any(item[0] == serial for item in results))
        self.assertEqual(results, [(serial, ImeSetResult(False, None, 'backend_error'))])

    def test_superseded_asynchronous_failure_does_not_finish_latest_request_twice(self):
        def factory():
            raise OSError('fake native initialization failed')
        sync = self.make_sync(factory=factory)
        results = []
        sync.requestFinished.connect(lambda serial, result: results.append((serial, result)))
        sync.start()
        self.spin_until(lambda: bool(results))
        results.clear()
        first = sync.request(True, ENGLISH)
        second = sync.request(False, ENGLISH)
        self.assertEqual(results, [])
        self.spin_until(lambda: bool(results))
        self.assertGreater(second, first)
        self.assertEqual(results, [(second, ImeSetResult(False, None, 'backend_error'))])

    def test_capture_exception_finishes_asynchronously_without_worker_write(self):
        capture_threads = []
        def capture():
            capture_threads.append(threading.get_ident())
            raise OSError('fake foreground identity read failed')
        sync = self.make_sync(target_factory=capture)
        sync.start()
        self.spin_until(lambda: sync.latest is not None)
        results = []
        sync.requestFinished.connect(lambda serial, result: results.append((serial, result)))
        serial = sync.request(True)
        self.assertEqual(results, [])
        self.spin_until(lambda: bool(results))
        self.assertEqual(capture_threads, [self.gui_thread])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], serial)
        self.assertFalse(results[0][1].ok)
        self.assertTrue(results[0][1].reason)
        self.assertFalse(any(call[0] == 'set' for call in self.backends[0].calls))

    def test_transient_unknown_result_recovers_original_state_without_external_change(self):
        unknown = replace(ENGLISH, chinese=None, reason='message_timeout')
        def capture_failure():
            raise OSError('temporary foreground read failure')
        for failure in ('write', 'capture'):
            with self.subTest(failure=failure):
                sync = self.make_sync(
                    target_factory=capture_failure if failure == 'capture' else None,
                    set_chinese=lambda *_: ImeSetResult(False, unknown, 'message_timeout'))
                states, completed = [], []
                sync.stateChanged.connect(states.append)
                sync.requestFinished.connect(
                    lambda serial, result, owner=sync, output=completed:
                    output.append((result, owner.latest)))
                sync.start()
                self.spin_until(lambda: sync.latest == ENGLISH)
                backend = self.backends[-1]
                self.assertEqual(states, [ENGLISH])
                sync.request(True, ENGLISH if failure == 'write' else None)
                self.spin_until(lambda: bool(completed))
                self.assertFalse(completed[0][0].ok)
                self.assertEqual(completed[0][1], unknown if failure == 'write' else None)
                # The OS remains English, equal to the worker's pre-request
                # observation. It must still repair the GUI's unknown state.
                self.spin_until(lambda: sync.latest == ENGLISH and len(states) >= 2)
                self.assertEqual(states, [ENGLISH, ENGLISH])
                calls_after_recovery = len(backend.calls)
                self.spin_until(lambda: len(backend.calls) >= calls_after_recovery + 3)
                self.assertEqual(states, [ENGLISH, ENGLISH])
                self.assertFalse(sync._failed)
                sync.stop()

    def test_close_exception_is_logged_without_escaping_worker(self):
        escaped = []
        def close():
            raise OSError('fake native close failed')
        sync = self.make_sync(close=close)
        with patch('threading.excepthook', side_effect=escaped.append), \
                self.assertLogs(level='ERROR') as logs:
            sync.start()
            self.spin_until(lambda: sync.latest is not None)
            sync.stop()
        self.assertEqual(escaped, [])
        self.assertIn('Unable to close the IME backend', logs.output[0])
        self.assertEqual(self.backends[0].calls[-1][1], self.backends[0].created_thread)

    def test_target_guard_is_read_only_and_delegates_to_native_identity_check(self):
        with patch('ime_sync.NativeImeBackend.target_matches', return_value=True) as target:
            self.assertFalse(ImeSynchronizer.target_matches(None))
            target.assert_not_called()
            self.assertTrue(ImeSynchronizer.target_matches(ENGLISH))
            target.assert_called_once_with(ENGLISH)


if __name__ == '__main__':
    unittest.main()
