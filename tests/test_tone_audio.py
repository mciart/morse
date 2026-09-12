"""Deterministic PCM and lifecycle checks; never open a real audio device."""

from array import array
import os
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtMultimedia import QAudio, QAudioFormat
from PyQt5.QtCore import QBuffer, QEvent, QIODevice, QObject, pyqtSignal
from PyQt5 import sip

from tone_audio import ToneAudio, ToneRenderer, _ToneOutput


def pcm_samples(data):
    result = array("h")
    result.frombytes(data)
    if sys.byteorder != "little":
        result.byteswap()
    return result


class ToneRendererTests(unittest.TestCase):
    def test_silence_and_stereo_frame_format(self):
        renderer = ToneRenderer()
        self.assertEqual(renderer.render(137), bytes(137 * 4))
        renderer.set_tone(True)
        samples = pcm_samples(renderer.render(480))
        self.assertEqual(len(samples), 960)
        self.assertEqual(samples[::2], samples[1::2])

    def test_default_frequency_and_six_millisecond_envelope(self):
        renderer = ToneRenderer(channels=1, volume=1)
        renderer.set_tone(True)
        samples = pcm_samples(renderer.render(4800))
        self.assertEqual(samples[0], 0)
        self.assertLess(max(abs(x) for x in samples[:48]), 4000)
        self.assertGreater(max(abs(x) for x in samples[288:480]), 22000)
        # Stable 600 Hz is one positive-going crossing every 80 samples at 48 kHz.
        crossings = [i for i in range(401, 4800) if samples[i - 1] <= 0 < samples[i]]
        self.assertTrue(all(b - a == 80 for a, b in zip(crossings, crossings[1:])))
        renderer.set_tone(False)
        release = pcm_samples(renderer.render(480))
        self.assertTrue(any(release[:200]))
        self.assertTrue(all(x == 0 for x in release[288:]))

    def test_chunk_boundaries_preserve_waveform_and_confirmation_never_stops_tone(self):
        whole = ToneRenderer()
        chunked = ToneRenderer()
        whole.set_tone(True)
        chunked.set_tone(True)
        self.assertEqual(whole.render(1500), chunked.render(257) + chunked.render(1243))
        chunked.confirm()
        mixed = pcm_samples(chunked.render(3000))
        self.assertTrue(chunked.tone)
        self.assertIsNone(chunked._confirmation)
        self.assertTrue(any(mixed[-200:]))
        self.assertLess(max(abs(value) for value in mixed), 32767)

    def test_muted_renderer_is_silent_even_with_active_oscillators(self):
        renderer = ToneRenderer()
        renderer.set_tone(True)
        renderer.confirm(False)
        renderer.enabled = False
        self.assertEqual(renderer.render(1000), bytes(4000))

    def test_first_dot_survives_on_and_off_before_any_audio_timer_tick(self):
        renderer = ToneRenderer(sample_rate=48000, channels=1)
        renderer.queue_tone(True, 10.0)
        renderer.queue_tone(False, 10.08)
        samples = pcm_samples(renderer.render(4800))
        self.assertTrue(any(samples[480:3360]))  # The first 80 ms dot is audible.
        self.assertTrue(all(value == 0 for value in samples[4128:]))
        self.assertFalse(renderer.tone)

    def test_batched_edges_preserve_dot_dash_lengths_and_gap(self):
        renderer = ToneRenderer(sample_rate=48000, channels=1)
        for active, timestamp in ((True, 10), (False, 10.08), (True, 10.16), (False, 10.4)):
            renderer.queue_tone(active, timestamp)
        samples = pcm_samples(renderer.render(24000))
        self.assertTrue(any(samples[480:3360]))
        self.assertTrue(all(value == 0 for value in samples[4800:7200]))
        self.assertTrue(any(samples[8200:18720]))
        self.assertTrue(all(value == 0 for value in samples[19680:]))

    def test_reset_discards_queued_edges_and_new_input_after_idle_starts_immediately(self):
        renderer = ToneRenderer(channels=1)
        renderer.queue_tone(True, 10)
        renderer.queue_tone(False, 10.08)
        renderer.reset()
        self.assertEqual(renderer.render(4800), bytes(9600))
        renderer.queue_tone(True, 20)
        renderer.queue_tone(False, 20.08)
        self.assertTrue(any(pcm_samples(renderer.render(4800))))
        renderer.queue_tone(True, 50)
        renderer.queue_tone(False, 50.08)
        self.assertTrue(any(pcm_samples(renderer.render(4800))))

    def test_long_stale_catchup_is_discarded_instead_of_playing_a_burst(self):
        renderer = ToneRenderer(channels=1)
        renderer.queue_tone(True, 10)
        renderer.queue_tone(False, 12)
        self.assertEqual(renderer.render(96000), bytes(192000))
        self.assertFalse(renderer.tone)


class ToneAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.device_patch = patch("tone_audio.QAudioDeviceInfo", Mock())
        self.device = self.device_patch.start()
        self.audio = ToneAudio(backend_enabled=False)

    def tearDown(self):
        self.audio.shutdown()
        self.audio.deleteLater()
        self.device_patch.stop()

    def test_lazy_disabled_backend_never_queries_devices(self):
        self.audio.prepare()
        self.audio.configure(frequency=700, volume=0.2, confirmation_enabled=True)
        self.audio.set_tone(True)
        self.audio.confirm()
        self.audio.set_device("test device")
        self.assertEqual(self.audio.renderer.frequency, 700)
        self.assertEqual(self.audio.renderer.volume, 0.2)
        self.assertTrue(self.audio.renderer.tone)
        self.assertFalse(self.audio._timer.isActive())
        self.device.defaultOutputDevice.assert_not_called()
        self.device.availableDevices.assert_not_called()

    def test_prepare_opens_no_voice_and_does_not_start_when_muted_or_closed(self):
        with patch.object(self.audio, '_ensure_started') as start:
            self.audio.prepare()
            start.assert_called_once_with()
            self.assertFalse(self.audio.renderer.tone)
            self.assertIsNone(self.audio.renderer._confirmation)
            self.assertIsNone(self.audio.renderer._preview)
            self.assertEqual(self.audio.renderer.render(120), bytes(480))
            self.audio.configure(enabled=False)
            self.audio.prepare()
            self.audio.shutdown()
            self.audio.prepare()
            start.assert_called_once_with()

    def test_windows_buffer_keeps_native_blocks_large_enough_for_realtime_output(self):
        with patch('tone_audio.sys.platform', 'win32'):
            audio = ToneAudio(backend_enabled=False)
        try:
            self.assertEqual(audio._buffer_frames, 1920)
            self.assertGreaterEqual(audio._buffer_frames / 5 / 48000 * 1000, 8)
        finally:
            audio.shutdown()
            audio.deleteLater()

    def test_confirmation_is_optional_and_mute_clears_both_voices(self):
        self.audio.confirm()
        self.assertIsNone(self.audio.renderer._confirmation)
        self.audio.configure(confirmation_enabled=True)
        self.audio.confirm(False)
        self.assertIsNotNone(self.audio.renderer._confirmation)
        self.audio.set_tone(True)
        self.audio.configure(enabled=False)
        self.assertEqual(self.audio.renderer.render(120), bytes(480))
        self.assertFalse(self.audio.renderer.tone)

    def test_reapplying_settings_preserves_the_running_device_and_retry_remains_possible(self):
        output = Mock()
        self.audio._output = output
        self.audio._push_device = Mock()
        self.audio.configure(frequency=720, volume=0.4)
        self.audio.set_device('')  # An empty saved preference means the default.
        self.audio.set_device(None)
        self.assertIs(self.audio._output, output)
        output.stop.assert_not_called()
        self.audio.set_device('Headphones')
        output.stop.assert_called_once()
        self.assertEqual(self.audio._device_choice, 'Headphones')
        self.audio.renderer.set_tone(True)
        self.audio._failed = True
        with patch.object(self.audio, '_ensure_started') as restart:
            self.audio.set_device('Headphones')
        restart.assert_called_once()
        self.assertFalse(self.audio._failed)

    def test_preview_is_bounded_and_does_not_change_the_muted_setting(self):
        self.audio.configure(enabled=False)
        self.audio.preview(100)
        self.assertFalse(self.audio.renderer.enabled)
        samples = pcm_samples(self.audio.renderer.render(6000))
        self.assertTrue(any(samples[:9600]))
        self.assertTrue(all(value == 0 for value in samples[9600:]))
        self.assertIsNone(self.audio.renderer._preview)
        self.audio.preview()
        self.audio.stop()
        self.assertEqual(self.audio.renderer.render(120), bytes(480))

    def test_shutdown_stops_timer_then_native_output_and_is_idempotent(self):
        output = Mock()
        order = []
        output.stop.side_effect = lambda: order.append(
            (self.audio._timer.isActive(), self.audio._push_device, self.audio._output)
        )
        self.audio._output = output
        self.audio._push_device = Mock()
        self.audio._timer.start()
        self.audio.shutdown()
        self.audio.shutdown()
        self.assertEqual(order, [(False, None, None)])
        output.stop.assert_called_once_with()
        output.deleteLater.assert_called_once_with()
        self.audio.set_tone(True)
        self.audio.confirm()
        self.assertFalse(self.audio.renderer.tone)

    def test_partial_native_writes_are_retained_without_skipping_samples(self):
        self.audio._buffer_frames = 960
        output = Mock()
        output.bufferSize.return_value = 3840
        output.bytesFree.return_value = 3840
        pushed = []
        push_device = Mock()

        def write(data):
            written = min(len(data), 256)
            pushed.append(bytes(data[:written]))
            return written

        push_device.write.side_effect = write
        self.audio._output = output
        self.audio._push_device = push_device
        self.audio.renderer.set_tone(True)
        expected = ToneRenderer()
        expected.set_tone(True)
        for _ in range(15):
            self.audio._feed()
        self.assertEqual(b"".join(pushed), expected.render(960))
        self.assertEqual(self.audio._pending, b"")

    def test_large_driver_buffer_does_not_add_extra_queued_latency(self):
        self.audio._buffer_frames = 960
        output = Mock()
        output.bufferSize.return_value = 38400
        output.bytesFree.return_value = 38016  # Already queued: 2 ms.
        push_device = Mock()
        push_device.write.side_effect = len
        self.audio._output = output
        self.audio._push_device = push_device
        self.audio._feed()
        self.assertEqual(len(push_device.write.call_args.args[0]), 3456)  # 18 ms.
        output.bytesFree.return_value = 34560  # Already queued: full 20 ms.
        self.audio._feed()
        push_device.write.assert_called_once()

    def test_startup_failure_is_reported_and_native_resources_are_released(self):
        self.audio._backend_enabled = True
        device = Mock()
        device.isNull.return_value = False
        self.audio._resolve_device = Mock(return_value=device)
        audio_format = QAudioFormat()
        audio_format.setSampleRate(48000)
        audio_format.setChannelCount(2)
        errors = []
        self.audio.error.connect(errors.append)
        output = Mock()
        output.start.return_value = None
        output.error.return_value = QAudio.OpenError
        with patch.object(self.audio, "_choose_format", return_value=audio_format), \
                patch("tone_audio.QAudioOutput", return_value=output):
            self.audio.set_tone(True)
        self.assertEqual(len(errors), 1)
        self.assertIsNone(self.audio._output)
        self.assertIsNone(self.audio._push_device)
        self.assertFalse(self.audio._timer.isActive())
        output.stop.assert_called_once()

    def test_write_failure_cannot_restart_timer_after_releasing_output(self):
        self.audio._backend_enabled = True
        device = Mock()
        device.isNull.return_value = False
        self.audio._resolve_device = Mock(return_value=device)
        audio_format = QAudioFormat()
        audio_format.setSampleRate(48000)
        audio_format.setChannelCount(2)
        output = Mock()
        output.bufferSize.return_value = 3840
        output.bytesFree.return_value = 3840
        output.error.return_value = QAudio.NoError
        output.start.return_value.write.return_value = -1
        with patch.object(self.audio, "_choose_format", return_value=audio_format), \
                patch("tone_audio.QAudioOutput", return_value=output):
            self.audio.set_tone(True)
        self.assertIsNone(self.audio._output)
        self.assertFalse(self.audio._timer.isActive())

    def test_native_endpoint_is_deleted_after_feeding_stops_before_parent_destruction(self):
        class FakeOutput(QObject):
            stateChanged = pyqtSignal(QAudio.State)

            def __init__(self, device, audio_format, parent):
                super().__init__(parent)
                self.endpoint = QBuffer(self)
                self.endpoint.open(QIODevice.ReadWrite)
                self.capacity = 3840

            def start(self):
                return self.endpoint

            def stop(self):
                self.endpoint.close()

            def error(self):
                return QAudio.NoError

            def setBufferSize(self, size):
                self.capacity = size

            def bufferSize(self):
                return self.capacity

            def bytesFree(self):
                return self.capacity

            def setVolume(self, value):
                pass

        parent = QObject()
        audio = ToneAudio(parent, backend_enabled=False)
        audio._backend_enabled = True
        audio._buffer_ms = 20
        device = Mock()
        device.isNull.return_value = False
        audio._resolve_device = Mock(return_value=device)
        audio_format = QAudioFormat()
        audio_format.setSampleRate(48000)
        audio_format.setChannelCount(2)
        with patch.object(audio, '_choose_format', return_value=audio_format), \
                patch('tone_audio.QAudioOutput', FakeOutput):
            audio.prepare()
            output, endpoint = audio._output, audio._push_device
            self.assertEqual(endpoint.size(), 3840)
            self.assertEqual(bytes(endpoint.data()), bytes(3840))
            audio.set_device('Another output')
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.assertTrue(sip.isdeleted(output))
            self.assertTrue(sip.isdeleted(endpoint))
            replacement = audio._output
            audio.shutdown()
            parent.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.assertTrue(sip.isdeleted(replacement))
            self.assertTrue(sip.isdeleted(audio))
            self.assertTrue(sip.isdeleted(parent))


class AudioThreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_audio_keeps_feeding_during_a_blocked_gui_and_worker_shutdown_owns_cleanup(self):
        created = threading.Event()
        packets, outputs, callback_threads = [], [], []
        gui_thread = threading.get_ident()

        class Endpoint:
            def write(self, data):
                callback_threads.append(threading.get_ident())
                packets.append(bytes(data))
                return len(data)

        class NativeOutput(QObject):
            stateChanged = pyqtSignal(QAudio.State)

            def __init__(self, device, audio_format, parent):
                super().__init__(parent)
                self.endpoint = Endpoint()
                self.capacity = 7680
                outputs.append(self)
                callback_threads.append(threading.get_ident())
                created.set()

            def start(self):
                return self.endpoint

            def stop(self):
                callback_threads.append(threading.get_ident())

            def error(self):
                return QAudio.NoError

            def setBufferSize(self, size):
                self.capacity = size

            def bufferSize(self):
                return self.capacity

            def bytesFree(self):
                return self.capacity

            def setVolume(self, value):
                pass

        device = Mock()
        device.isNull.return_value = False
        audio_format = QAudioFormat()
        audio_format.setSampleRate(48000)
        audio_format.setChannelCount(2)
        with patch.object(_ToneOutput, '_resolve_device', return_value=device), \
                patch.object(_ToneOutput, '_choose_format', return_value=audio_format), \
                patch('tone_audio.QAudioOutput', NativeOutput):
            audio = ToneAudio()
            try:
                audio.prepare()
                self.assertTrue(created.wait(2))
                before = len(packets)
                # No Qt GUI event processing: a synchronous paint/layout can
                # block here while the audio thread must continue rendering.
                time.sleep(0.08)
                self.assertGreater(len(packets), before + 3)
                packets.clear()
                timestamp = time.monotonic()
                audio.set_tone(True, timestamp=timestamp)
                audio.set_tone(False, timestamp=timestamp + 0.08)
                time.sleep(0.08)
                self.assertTrue(any(value for packet in packets for value in packet))
                worker, thread = audio._worker, audio._audio_thread
                audio.shutdown()
                audio.shutdown()
                self.assertFalse(thread.isRunning())
                self.assertTrue(sip.isdeleted(worker))
                self.assertTrue(all(sip.isdeleted(output) for output in outputs))
                self.assertNotIn(gui_thread, callback_threads)
            finally:
                audio.shutdown()
                audio.deleteLater()

            # Programmatic window destruction also joins the thread before
            # QObject deletes the controller's QThread child.
            created.clear()
            parent = QObject()
            owned_audio = ToneAudio(parent)
            try:
                owned_audio.prepare()
                self.assertTrue(created.wait(2))
                worker = owned_audio._worker
                parent.deleteLater()
                self.app.sendPostedEvents(None, QEvent.DeferredDelete)
                self.assertTrue(sip.isdeleted(worker))
                self.assertTrue(sip.isdeleted(owned_audio))
            finally:
                if not sip.isdeleted(owned_audio):
                    owned_audio.shutdown()
                    parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
