"""Screen-aware settings sizing and form rows, in Qt logical pixels.

The controller only sizes the initial window to its content. Screen changes
subsequently constrain existing geometry, so normal user resizing is retained.
No display mode, DPI setting, or persisted application setting is changed.
"""

from PyQt5.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer
from PyQt5.QtGui import QTextLayout, QTextOption
from PyQt5.QtWidgets import (QApplication, QBoxLayout, QCheckBox, QComboBox,
                             QFormLayout, QKeySequenceEdit, QLabel, QSizePolicy,
                             QStyle, QStyleOptionComboBox, QWidget)


def settings_client_size(content_hint, actions_hint, available, *, margins=24,
                         frame=QSize(16, 40), preferred_width=560, scale=1.0):
    """Choose a readable first size while leaving the complete frame on screen."""
    margins = round(margins * scale)
    maximum = QSize(max(1, available.width() - margins - frame.width()),
                    max(1, available.height() - margins - frame.height()))
    width = max(round(preferred_width * scale), content_hint.width() + margins + round(20 * scale),
                actions_hint.width() + margins)
    # Very long descriptions should wrap, rather than making a desktop-wide form.
    width = min(width, round(760 * scale), maximum.width())
    height = max(round(240 * scale), content_hint.height() + actions_hint.height() + margins + round(12 * scale))
    return QSize(width, min(height, maximum.height()))


def fit_settings_frame(frame, available, margin=12):
    """Clamp size and position, including screens left or above the primary."""
    horizontal = min(margin, max(0, (available.width() - 1) // 2))
    vertical = min(margin, max(0, (available.height() - 1) // 2))
    bounds = available.adjusted(horizontal, vertical, -horizontal, -vertical)
    size = QSize(min(frame.width(), bounds.width()), min(frame.height(), bounds.height()))
    left = min(max(frame.left(), bounds.left()), bounds.right() - size.width() + 1)
    top = min(max(frame.top(), bounds.top()), bounds.bottom() - size.height() + 1)
    return QRect(QPoint(left, top), size)


class ResponsiveSettingsRow(QBoxLayout):
    """Keep controls side by side while they fit; stack them on narrow screens."""

    def __init__(self, parent=None):
        super().__init__(QBoxLayout.LeftToRight, parent)

    def setGeometry(self, rect):
        margins = self.contentsMargins()
        items = [self.itemAt(index) for index in range(self.count())
                 if not self.itemAt(index).isEmpty()]
        required = sum(item.minimumSize().width() for item in items)
        required += max(0, len(items) - 1) * max(0, self.spacing())
        available = rect.width() - margins.left() - margins.right()
        direction = self.TopToBottom if required > available else self.LeftToRight
        if self.direction() != direction:
            self.setDirection(direction)
        super().setGeometry(rect)

    def minimumSize(self):
        # A horizontal minimum must not prevent setGeometry from seeing a
        # narrow rectangle and changing direction in the first place.
        size = super().minimumSize()
        widths = [self.itemAt(index).minimumSize().width() for index in range(self.count())
                  if not self.itemAt(index).isEmpty()]
        margins = self.contentsMargins()
        size.setWidth(max(widths, default=0) + margins.left() + margins.right())
        return size


class ResponsiveSettingsForm(QFormLayout):
    """Two-column form whose field moves below its label when space is tight."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setFormAlignment(Qt.AlignTop)


def wrap_checkbox_text(checkbox, width):
    """Wrap a static checkbox caption without dropping or eliding its text."""
    original = checkbox.property('_settings_caption')
    if original is None:
        original = checkbox.text()
        checkbox.setProperty('_settings_caption', original)
    spacing = checkbox.style().pixelMetric(QStyle.PM_CheckBoxLabelSpacing, None, checkbox)
    indicator = checkbox.style().pixelMetric(QStyle.PM_IndicatorWidth, None, checkbox)
    line_width = max(1, width - indicator - spacing - 8)
    lines = []
    for paragraph in original.split('\n'):
        layout = QTextLayout(paragraph, checkbox.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(line_width)
            lines.append(paragraph[line.textStart():line.textStart() + line.textLength()].rstrip())
        layout.endLayout()
        if not paragraph:
            lines.append('')
    text = '\n'.join(lines)
    if checkbox.text() != text:
        checkbox.setText(text)


class SettingsWindowSizer(QObject):
    """Attach after the settings layout is built; retain as a window attribute.

    ``screen_provider`` is an optional geometry provider for isolated tests.
    In production screen/DPI signals are connected to the window's current
    QScreen. A normal resize only reflows content; it never restores a preset.
    """

    def __init__(self, window, scroll, actions, *, screen_provider=None):
        super().__init__(window)
        self.window = window
        self.scroll = scroll
        self.actions = actions
        self._screen_provider = screen_provider
        self._screen = None
        self._handle = None
        self._initial = True
        self._constrain = False
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._refresh)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setWidgetResizable(True)
        content = self.scroll.widget()
        content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        content.setMinimumWidth(0)
        for label in content.findChildren(QLabel):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
        for combo in content.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.currentIndexChanged.connect(lambda *args: self.schedule())
        for shortcut in content.findChildren(QKeySequenceEdit):
            shortcut.keySequenceChanged.connect(lambda *args: self.schedule())
        window.installEventFilter(self)
        self.scroll.viewport().installEventFilter(self)
        content.installEventFilter(self)
        for group in content.findChildren(QWidget):
            if group.layout() is not None:
                group.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.window:
            if event.type() in (QEvent.Show, QEvent.WinIdChange):
                self._connect_screen()
                if event.type() == QEvent.Show and self._initial:
                    # Resolve the first size during show, not in a later
                    # timer that could overwrite an immediate user resize.
                    self._refresh()
                self.schedule(constrain=True)
            elif event.type() in (QEvent.FontChange, QEvent.StyleChange,
                                  QEvent.ApplicationFontChange):
                self.schedule(constrain=True)
            elif event.type() == QEvent.WindowStateChange:
                self.schedule(constrain=True)
            elif event.type() == QEvent.Resize:
                self.schedule()
        elif event.type() in (QEvent.Resize, QEvent.LayoutRequest):
            self.schedule()
        return False

    def _connect_screen(self, screen=None):
        handle = self.window.windowHandle()
        if handle is not None and handle is not self._handle:
            if self._handle is not None:
                try:
                    self._handle.screenChanged.disconnect(self._screen_changed)
                except (TypeError, RuntimeError):
                    pass
            self._handle = handle
            handle.screenChanged.connect(self._screen_changed)
        screen = screen or (handle.screen() if handle else QApplication.primaryScreen())
        if screen is self._screen:
            return
        if self._screen is not None:
            for name in ('availableGeometryChanged', 'geometryChanged', 'logicalDotsPerInchChanged'):
                try:
                    getattr(self._screen, name).disconnect(self._screen_metrics_changed)
                except (TypeError, RuntimeError):
                    pass
        self._screen = screen
        if screen is not None:
            for name in ('availableGeometryChanged', 'geometryChanged', 'logicalDotsPerInchChanged'):
                getattr(screen, name).connect(self._screen_metrics_changed)

    def _screen_changed(self, screen):
        self._connect_screen(screen)
        self.schedule(constrain=True)

    def _screen_metrics_changed(self, *args):
        self.schedule(constrain=True)

    def schedule(self, *, constrain=False):
        if self._busy:
            return
        self._constrain = self._constrain or constrain
        self._timer.start(0)

    def available_geometry(self):
        if self._screen_provider is not None:
            return QRect(self._screen_provider())
        self._connect_screen()
        return self._screen.availableGeometry() if self._screen else QRect(0, 0, 800, 600)

    def _refresh(self):
        if self._busy or not self.window.isVisible():
            return
        self._busy = True
        try:
            if not (self.window.isMinimized() or self.window.isMaximized()):
                if self._initial or self._constrain:
                    self.fit_to_screen(initial=self._initial)
                    self._initial = False
                    self._constrain = False
            self.reflow()
        finally:
            self._busy = False

    def reflow(self):
        content = self.scroll.widget()
        # The selected value must remain readable even when it is wider than
        # the combo's usual minimum. Its responsive row can then stack instead
        # of squeezing a long choice (such as Ctrl+Alt+Shift+M or mouse X1).
        for combo in content.findChildren(QComboBox):
            option = QStyleOptionComboBox()
            combo.initStyleOption(option)
            metrics = combo.fontMetrics()
            text = QSize(metrics.horizontalAdvance(combo.currentText()) + 8, metrics.height())
            required = combo.style().sizeFromContents(QStyle.CT_ComboBox, option, text, combo)
            combo.setMinimumWidth(required.width())
        for shortcut in content.findChildren(QKeySequenceEdit):
            text = shortcut.keySequence().toString()
            shortcut.setMinimumWidth(shortcut.fontMetrics().horizontalAdvance(text) + 36)
        content.layout().activate()
        for checkbox in content.findChildren(QCheckBox):
            remaining = self.scroll.viewport().width() - checkbox.mapTo(content, QPoint()).x() - 16
            wrap_checkbox_text(checkbox, max(40, min(checkbox.width(), remaining)))
        content.updateGeometry()

    def fit_to_screen(self, *, initial=False):
        available = self.available_geometry()
        # This app also runs without Qt's coordinate scaling: at 300% Windows
        # DPI, QScreen can report physical-size geometry and logicalDpi=288
        # while devicePixelRatio remains 1. Scale constants by logical DPI;
        # when Qt already scales coordinates its logical DPI stays near 96.
        scale = max(0.5, self.window.logicalDpiX() / 96.0)
        frame = self.window.frameGeometry()
        client = self.window.geometry()
        frame_extra = QSize(max(0, frame.width() - client.width()),
                            max(0, frame.height() - client.height()))
        if initial:
            hint = self.scroll.widget().sizeHint()
            size = settings_client_size(hint, self.actions.sizeHint(), available,
                                        frame=frame_extra, scale=scale)
            self.window.setMinimumSize(min(round(320 * scale), size.width()),
                                       min(round(240 * scale), size.height()))
            self.window.resize(size)
            frame = self.window.frameGeometry()
            frame.moveCenter(available.center())
        fitted = fit_settings_frame(frame, available, margin=round(12 * scale))
        size = QSize(max(1, fitted.width() - frame_extra.width()),
                     max(1, fitted.height() - frame_extra.height()))
        self.window.setMinimumSize(min(round(320 * scale), size.width()),
                                   min(round(240 * scale), size.height()))
        if self.window.size() != size:
            self.window.resize(size)
        if self.window.frameGeometry().topLeft() != fitted.topLeft():
            self.window.move(fitted.topLeft())
