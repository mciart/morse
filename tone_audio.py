"""Continuous sidetone on an owned Qt audio thread with timed PCM edges.

The GUI queues commands; a dedicated Qt event loop owns the native push audio
device and its timer. No Python QIODevice or native audio callback is used.
"""

from array import array
from collections import deque
import math
import sys
import time

from PyQt5.QtCore import (QCoreApplication, QMetaObject, QObject, QThread, QTimer,
                         Qt, pyqtSignal, pyqtSlot)
from PyQt5.QtMultimedia import QAudio, QAudioDeviceInfo, QAudioFormat, QAudioOutput


class ToneRenderer:
    """Stateful signed 16-bit little-endian PCM generator, independent of Qt."""

    def __init__(self, sample_rate=48000, channels=2, frequency=600,
                 volume=0.3, envelope_ms=6):
        if sample_rate <= 0 or channels not in (1, 2):
            raise ValueError("PCM requires a positive sample rate and one or two channels")
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.frequency = float(frequency)
        self.volume = max(0.0, min(1.0, float(volume)))
        self.enabled = True
        self.tone = False
        self._phase = 0.0
        self._silence_phase = None
        self._level = 0.0
        self._ramp_frames = max(1, round(self.sample_rate * envelope_ms / 1000))
        self._confirmation = None
        self._confirmation_phase = 0.0
        self._preview = None
        self._preview_phase = 0.0
        self._playing_tone = False
        self._frame = 0
        self._edges = deque()
        self._origin_time = None
        self._origin_frame = 0
        self._last_edge_time = None

    @property
    def bytes_per_frame(self):
        return self.channels * 2

    def set_tone(self, active):
        self.tone = bool(active)
        self._playing_tone = self.tone
        self._edges.clear()
        self._origin_time = self._last_edge_time = None

    def queue_tone(self, active, timestamp):
        """Keep mark lengths even when both edges arrive before the next render.

        Late starts anchor at the next available PCM frame. Their later stop
        edge retains its timestamp distance, instead of overwriting a gate.
        Playback may lag a delayed producer, but never queues more than 1 s.
        """
        active, timestamp = bool(active), float(timestamp)
        if not math.isfinite(timestamp):
            raise ValueError("Tone timestamps must be finite")
        if active == self.tone:
            return
        if active and not self._playing_tone and not self._edges:
            # Silence was already sent while idle; a new input starts now.
            self._origin_time = self._last_edge_time = None
        if self._last_edge_time is not None:
            timestamp = max(timestamp, self._last_edge_time)
        if self._origin_time is None:
            self._origin_time = timestamp
            self._origin_frame = self._frame
        target = self._origin_frame + round((timestamp - self._origin_time) * self.sample_rate)
        if target < self._frame:
            if active:
                self._origin_frame += self._frame - target
            target = self._frame
        if target - self._frame > self.sample_rate:
            # Stale catch-up must not play a long burst after pause/suspend.
            self.reset()
            return
        self.tone = active
        self._last_edge_time = timestamp
        self._edges.append((target, active))

    def confirm(self, success=True):
        # A quiet additional oscillator never changes the Morse oscillator.
        duration = max(1, round(self.sample_rate * 0.055))
        self._confirmation = [0, duration, 840.0 if success else 330.0]
        self._confirmation_phase = 0.0

    def preview(self, duration_ms=250):
        duration = max(1, round(self.sample_rate * max(10, min(2000, duration_ms)) / 1000))
        self._preview = [0, duration]
        self._preview_phase = 0.0

    def stop(self):
        self.set_tone(False)
        self._confirmation = None
        self._preview = None

    def reset(self):
        self.stop()
        self._level = 0.0
        self._phase = 0.0
        self._silence_phase = None

    def _advance_silence(self, frame_count, phase_step):
        # Use one origin for the entire silent span: advancing each render
        # chunk separately would make the next audible phase depend on its size.
        if self._silence_phase is None or self._silence_phase[2] != phase_step:
            self._silence_phase = (self._phase, self._frame, phase_step)
        phase, origin, _ = self._silence_phase
        self._frame += frame_count
        self._phase = (phase + (self._frame - origin) * phase_step) % math.tau

    def render(self, frame_count):
        frame_count = max(0, int(frame_count))
        if not self.enabled:
            self._level = 0.0
            self._confirmation = None
        samples = array("h")
        phase_step = math.tau * self.frequency / self.sample_rate
        ramp_step = 1.0 / self._ramp_frames
        remaining = frame_count
        while remaining:
            while self._edges and self._edges[0][0] <= self._frame:
                _, self._playing_tone = self._edges.popleft()
            target = 1.0 if self._playing_tone and self.enabled else 0.0
            segment_frames = min(remaining, self._edges[0][0] - self._frame) if self._edges else remaining
            if (target == 0.0 and self._level == 0.0
                    and self._confirmation is None and self._preview is None):
                self._advance_silence(segment_frames, phase_step)
                samples.frombytes(bytes(segment_frames * self.bytes_per_frame))
                remaining -= segment_frames
                continue
            self._silence_phase = None
            # The gate stays fixed until the next queued edge. Keep the sound
            # loop free of per-sample queue lookups; only an ended fade/extra
            # oscillator can bring this segment back to the silence path early.
            for rendered in range(1, segment_frames + 1):
                if self._level < target:
                    self._level = min(target, self._level + ramp_step)
                elif self._level > target:
                    self._level = max(target, self._level - ramp_step)
                value = 0.7 * self._level * math.sin(self._phase)
                self._phase = (self._phase + phase_step) % math.tau
                if self._confirmation is not None:
                    position, duration, frequency = self._confirmation
                    fade = min(1.0, position / self._ramp_frames,
                               (duration - position) / self._ramp_frames)
                    value += 0.12 * fade * math.sin(self._confirmation_phase)
                    self._confirmation_phase = (
                        self._confirmation_phase + math.tau * frequency / self.sample_rate
                    ) % math.tau
                    self._confirmation[0] += 1
                    if self._confirmation[0] >= duration:
                        self._confirmation = None
                if self._preview is not None:
                    position, duration = self._preview
                    fade = min(1.0, position / self._ramp_frames,
                               (duration - position) / self._ramp_frames)
                    # The Morse sidetone takes priority over the test tone.
                    value += 0.7 * (1.0 - self._level) * fade * math.sin(self._preview_phase)
                    self._preview_phase = (self._preview_phase + phase_step) % math.tau
                    self._preview[0] += 1
                    if self._preview[0] >= duration:
                        self._preview = None
                sample = round(value * self.volume * 32767)
                samples.extend([sample] * self.channels)
                if (target == 0.0 and self._level == 0.0
                        and self._confirmation is None and self._preview is None):
                    break
            self._frame += rendered
            remaining -= rendered
        if sys.byteorder != "little":
            samples.byteswap()
        return samples.tobytes()


class _ToneOutput(QObject):
    """Lazy persistent audio output; call shutdown before destroying the window.

    ``volume`` is a fraction between 0 and 1. ``backend_enabled=False`` allows
    deterministic silent tests without even querying the machine's devices.
    ``set_device(None)`` selects the system default output.
    """

    error = pyqtSignal(str)

    def __init__(self, parent=None, *, backend_enabled=True, connect_quit=True):
        super().__init__(parent)
        self.renderer = ToneRenderer()
        self.confirmation_enabled = False
        self._backend_enabled = backend_enabled
        self._device_choice = None
        self._output = None
        self._push_device = None
        self._pending = b""
        self._closed = False
        self._failed = False
        # Qt 5's WinMM backend splits its buffer into five native blocks. A
        # 20 ms buffer produces 4 ms blocks that some Windows devices consume
        # at only half real time without reporting an underrun. Keep at least
        # 40 ms queued there; the GUI pump can still refill every 5 ms.
        self._buffer_ms = 40 if sys.platform == "win32" else 20
        self._buffer_frames = round(self.renderer.sample_rate * self._buffer_ms / 1000)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(5)
        self._timer.timeout.connect(self._feed)
        app = QCoreApplication.instance()
        if app is not None and connect_quit:
            app.aboutToQuit.connect(self.shutdown)

    def _check_thread(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("ToneAudio must be controlled from its owning Qt thread")

    def configure(self, *, frequency=None, volume=None, enabled=None,
                  confirmation_enabled=None):
        self._check_thread()
        if self._closed:
            return
        if frequency is not None:
            self.renderer.frequency = max(100.0, min(2000.0, float(frequency)))
        if volume is not None:
            self.renderer.volume = max(0.0, min(1.0, float(volume)))
        if enabled is not None:
            self.renderer.enabled = bool(enabled)
            if not enabled:
                self.renderer.reset()
                self._release_output()
        if confirmation_enabled is not None:
            self.confirmation_enabled = bool(confirmation_enabled)
            if not confirmation_enabled:
                self.renderer._confirmation = None

    def set_tone(self, active, timestamp=None):
        self._check_thread()
        if self._closed:
            return
        if not self.renderer.enabled:
            return
        timestamp = time.monotonic() if timestamp is None else timestamp
        self.renderer.queue_tone(active, timestamp)
        if active and self.renderer.enabled:
            self._ensure_started()

    @pyqtSlot()
    def prepare(self):
        """Warm the output with silence before accepting the first Morse key."""
        self._check_thread()
        if not self._closed and self.renderer.enabled:
            self._ensure_started()

    def confirm(self, success=True):
        self._check_thread()
        if self._closed or not self.renderer.enabled or not self.confirmation_enabled:
            return
        self.renderer.confirm(success)
        self._ensure_started()

    def preview(self, duration_ms=250):
        """Play a bounded test tone without changing the global sound setting."""
        self._check_thread()
        if self._closed:
            return
        self.renderer.preview(duration_ms)
        self._ensure_started(force=True)

    def set_device(self, device=None):
        self._check_thread()
        if self._closed:
            return
        device = device or None
        if device == self._device_choice and not self._failed:
            # Settings such as pitch/volume also refresh the selected device.
            # Preserve the native stream unless the selection really changed.
            return
        self._device_choice = device
        was_started = self._output is not None
        self._release_output()
        self._failed = False
        if was_started or self.renderer.tone:
            self._ensure_started()

    def stop(self):
        self._check_thread()
        if self._closed:
            return
        self.renderer.reset()
        # Pause/reset also discards PCM already queued in the native device.
        self._release_output()

    @pyqtSlot()
    def shutdown(self):
        self._check_thread()
        if self._closed:
            return
        # Disable future timer work before invalidating the native push device.
        self._closed = True
        self._release_output()
        self.renderer.reset()

    def _resolve_device(self):
        if isinstance(self._device_choice, QAudioDeviceInfo):
            return self._device_choice
        if self._device_choice:
            for device in QAudioDeviceInfo.availableDevices(QAudio.AudioOutput):
                if device.deviceName() == self._device_choice:
                    return device
        return QAudioDeviceInfo.defaultOutputDevice()

    @staticmethod
    def _choose_format(device):
        for sample_rate in (48000, 44100, 22050):
            for channels in (2, 1):
                audio_format = QAudioFormat()
                audio_format.setSampleRate(sample_rate)
                audio_format.setChannelCount(channels)
                audio_format.setSampleSize(16)
                audio_format.setCodec("audio/pcm")
                audio_format.setByteOrder(QAudioFormat.LittleEndian)
                audio_format.setSampleType(QAudioFormat.SignedInt)
                if device.isFormatSupported(audio_format):
                    return audio_format
        return None

    def _ensure_started(self, *, force=False):
        if (self._closed or self._output is not None or self._failed
                or not self._backend_enabled or (not force and not self.renderer.enabled)):
            return
        device = self._resolve_device()
        audio_format = None if device.isNull() else self._choose_format(device)
        if audio_format is None:
            self._failed = True
            self.error.emit("音频设备不可用或不支持 PCM 输出，请重新选择音频设备。")
            return
        old_renderer = self.renderer
        self.renderer = ToneRenderer(
            audio_format.sampleRate(), audio_format.channelCount(),
            old_renderer.frequency, old_renderer.volume,
        )
        self.renderer.set_tone(old_renderer._playing_tone)
        self.renderer.enabled = old_renderer.enabled
        if old_renderer._edges:
            # Keep absolute event time when changing the PCM sample rate/cursor.
            ratio = self.renderer.sample_rate / old_renderer.sample_rate
            self.renderer.tone = old_renderer.tone
            self.renderer._origin_time = old_renderer._origin_time
            self.renderer._last_edge_time = old_renderer._last_edge_time
            self.renderer._origin_frame = round((old_renderer._origin_frame - old_renderer._frame) * ratio)
            self.renderer._edges = deque((max(0, round((frame - old_renderer._frame) * ratio)), active)
                                         for frame, active in old_renderer._edges)
        else:
            self.renderer.set_tone(old_renderer.tone)
        if old_renderer._confirmation is not None:
            self.renderer.confirm(old_renderer._confirmation[2] == 840.0)
        if old_renderer._preview is not None:
            remaining_ms = (old_renderer._preview[1] - old_renderer._preview[0]) * 1000 / old_renderer.sample_rate
            self.renderer.preview(remaining_ms)
        self._buffer_frames = max(1, round(audio_format.sampleRate() * self._buffer_ms / 1000))
        self._output = QAudioOutput(device, audio_format, self)
        self._output.setBufferSize(self._buffer_frames * self.renderer.bytes_per_frame)
        self._output.setVolume(1.0)  # The PCM generator applies the user's volume.
        self._push_device = self._output.start()
        if self._push_device is None or self._output.error() != QAudio.NoError:
            self._failed = True
            self._release_output()
            self.error.emit("无法启动音频输出，请重新选择音频设备。")
            return
        self._output.stateChanged.connect(self._state_changed)
        self._feed()
        if self._push_device is not None:
            self._timer.start()

    @pyqtSlot()
    def _feed(self):
        if self._closed or self._push_device is None or self._output is None:
            return
        frame_bytes = self.renderer.bytes_per_frame
        # Windows may enlarge the requested native buffer. Keep no more than
        # the selected target queued, rather than filling an arbitrarily large one.
        queued_bytes = max(0, self._output.bufferSize() - self._output.bytesFree())
        writable = min(self._output.bytesFree(),
                       self._buffer_frames * frame_bytes - queued_bytes)
        writable = max(0, writable - writable % frame_bytes)
        if writable == 0:
            return
        if not self._pending:
            self._pending = self.renderer.render(writable // frame_bytes)
        written = self._push_device.write(self._pending[:writable])
        if written < 0:
            self._failed = True
            self._release_output()
            self.error.emit("音频设备已断开，请重新选择音频设备。")
        else:
            self._pending = self._pending[written:]

    @pyqtSlot(QAudio.State)
    def _state_changed(self, state):
        if (not self._closed and self._output is not None
                and state == QAudio.StoppedState
                and self._output.error() != QAudio.NoError):
            self._failed = True
            self._release_output()
            self.error.emit("音频输出已停止，请重新选择音频设备。")

    def _release_output(self):
        self._timer.stop()
        self._pending = b""
        output = self._output
        self._push_device = None
        self._output = None
        if output is not None:
            try:
                output.stateChanged.disconnect(self._state_changed)
            except (TypeError, RuntimeError):
                pass
            output.stop()
            output.deleteLater()

    @pyqtSlot(str, object)
    def dispatch(self, command, arguments):
        if self._closed:
            return
        try:
            getattr(self, command)(**arguments)
        except Exception as error:
            self.renderer.reset()
            self._release_output()
            self._failed = True
            self.error.emit("音频处理失败：" + str(error))


class ToneAudio(_ToneOutput):
    """GUI-facing audio controller with an owned, persistent Qt worker thread.

    ``backend_enabled=False`` keeps deterministic in-process rendering for tests
    and never starts a thread or queries audio devices. ``set_tone`` accepts the
    Morse engine's monotonic timestamp, preserving short coalesced key events.
    """

    _commands = pyqtSignal(str, object)

    def __init__(self, parent=None, *, backend_enabled=True):
        super().__init__(parent, backend_enabled=backend_enabled)
        self._threaded = bool(backend_enabled)
        self._audio_thread = None
        self._worker = None
        if parent is not None:
            # QObject emits destroyed before deleting children. Join while the
            # controller and its QThread child are still valid, even if a
            # caller destroys its window without the normal application quit.
            parent.destroyed.connect(self.shutdown)

    def _send(self, command, arguments):
        if self._worker is not None and not self._closed:
            self._commands.emit(command, arguments)

    def _ensure_started(self, *, force=False):
        if not self._threaded:
            return super()._ensure_started(force=force)
        if (self._closed or self._failed or not self._backend_enabled
                or (not force and not self.renderer.enabled)):
            return
        if self._worker is None:
            worker = _ToneOutput(backend_enabled=True, connect_quit=False)
            worker.configure(frequency=self.renderer.frequency, volume=self.renderer.volume,
                             enabled=self.renderer.enabled,
                             confirmation_enabled=self.confirmation_enabled)
            worker._device_choice = self._device_choice
            worker._buffer_ms = self._buffer_ms
            thread = QThread(self)
            thread.setObjectName('Morse audio')
            worker.moveToThread(thread)
            self._commands.connect(worker.dispatch, Qt.QueuedConnection)
            worker.error.connect(self._worker_error, Qt.QueuedConnection)
            thread.finished.connect(worker.deleteLater)
            self._worker, self._audio_thread = worker, thread
            thread.start()
        self._send('prepare', {})

    @pyqtSlot(str)
    def _worker_error(self, message):
        if not self._closed:
            self._failed = True
            self.error.emit(message)

    def configure(self, *, frequency=None, volume=None, enabled=None,
                  confirmation_enabled=None):
        super().configure(frequency=frequency, volume=volume, enabled=enabled,
                          confirmation_enabled=confirmation_enabled)
        if getattr(self, '_threaded', False):
            self._send('configure', dict(frequency=frequency, volume=volume, enabled=enabled,
                                         confirmation_enabled=confirmation_enabled))

    def set_tone(self, active, timestamp=None):
        if not self._threaded:
            return super().set_tone(active, timestamp)
        self._check_thread()
        if self._closed or not self.renderer.enabled:
            return
        self.renderer.set_tone(active)
        if active:
            self._ensure_started()
        self._send('set_tone', dict(active=bool(active), timestamp=(
            time.monotonic() if timestamp is None else timestamp)))

    def confirm(self, success=True):
        if not self._threaded:
            return super().confirm(success)
        self._check_thread()
        if self._closed or not self.renderer.enabled or not self.confirmation_enabled:
            return
        self.renderer.confirm(success)
        self._ensure_started()
        self._send('confirm', dict(success=bool(success)))

    def preview(self, duration_ms=250):
        if not self._threaded:
            return super().preview(duration_ms)
        self._check_thread()
        if self._closed:
            return
        self.renderer.preview(duration_ms)
        self._ensure_started(force=True)
        self._send('preview', dict(duration_ms=duration_ms))

    def set_device(self, device=None):
        if not self._threaded:
            return super().set_device(device)
        self._check_thread()
        if self._closed:
            return
        # Pass device names across the queue rather than a Qt device wrapper.
        name = device.deviceName() if isinstance(device, QAudioDeviceInfo) else device
        name = name or None
        if name == self._device_choice and not self._failed:
            return
        self._device_choice = name
        self._failed = False
        self._send('set_device', dict(device=name))

    def stop(self):
        if not self._threaded:
            return super().stop()
        self._check_thread()
        if self._closed:
            return
        self.renderer.reset()
        self._send('stop', {})

    @pyqtSlot()
    def shutdown(self):
        if not getattr(self, '_threaded', False):
            return super().shutdown()
        self._check_thread()
        if self._closed:
            return
        self._closed = True
        self.renderer.reset()
        worker, thread = self._worker, self._audio_thread
        self._worker = self._audio_thread = None
        if thread is not None:
            if thread.isRunning():
                # Stop all timer/device work on its own thread before joining.
                QMetaObject.invokeMethod(worker, 'shutdown', Qt.BlockingQueuedConnection)
                thread.quit()
                thread.wait()
            thread.deleteLater()
