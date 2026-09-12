"""A single, spatial Morse guide for keyboard and mouse actions."""

from math import ceil, isfinite

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPen, QTransform
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGraphicsScene, QGraphicsView, QGridLayout,
    QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QSizePolicy, QStatusBar, QVBoxLayout, QWidget,
)

from ui_theme import THEME_COLORS
from windows_integration import show_guide_without_activation


def morse(code):
    return str(code).replace('1', '•').replace('2', '–')


class FeedbackLabel(QLabel):
    """Keep full feedback available without letting it widen the window."""

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(
            self._full_text, Qt.ElideRight, max(0, self.contentsRect().width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class InputFeedbackPanel(QFrame):
    """Small, unscaled input feedback, independent of the expensive key grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('inputFeedbackPanel')
        self._roles = frozenset()
        self._sounding = None
        self._result_success = True
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        content = QVBoxLayout(self)
        content.setContentsMargins(9, 5, 9, 5)
        content.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.dot_label = QLabel('• 点')
        self.dash_label = QLabel('– 划')
        for indicator in (self.dot_label, self.dash_label):
            indicator.setAlignment(Qt.AlignCenter)
            indicator.setMargin(3)
            indicator.setMinimumWidth(indicator.fontMetrics().horizontalAdvance('• 按住') + 10)
            indicator.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            top.addWidget(indicator)
        self.code_label = FeedbackLabel('等待输入')
        self.code_label.setObjectName('morseInput')
        code_font = QFont(QApplication.font())
        code_font.setPointSizeF(14)
        code_font.setBold(True)
        self.code_label.setFont(code_font)
        self.code_label.setAlignment(Qt.AlignCenter)
        top.addWidget(self.code_label, 1)
        content.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.setToolTip('字符确认进度；继续输入会重新计时。')
        content.addWidget(self.progress)
        self.result_label = FeedbackLabel('最近输入将显示在这里')
        self.result_label.setMinimumHeight(self.result_label.fontMetrics().height() + 2)
        content.addWidget(self.result_label)
        self.result_timer = QTimer(self)
        self.result_timer.setSingleShot(True)
        self.result_timer.setInterval(2400)
        self.result_timer.timeout.connect(self.clearResult)
        self.updateTheme()

    def setInputFeedback(self, held_roles=(), progress=0.0, sounding=None):
        roles = frozenset(held_roles)
        if roles != self._roles or sounding != self._sounding:
            self._roles, self._sounding = roles, sounding
            self._updateIndicators()
        self.progress.setValue(round(max(0.0, min(1.0, float(progress))) * 1000))

    def _updateIndicators(self):
        self.dot_label.setText('• 按住' if 'straight' in self._roles else '• 点')
        for label, role in ((self.dot_label, 'dot'), (self.dash_label, 'dash')):
            pressed = role in self._roles or (role == 'dot' and 'straight' in self._roles)
            sounding = self._sounding == role or (role == 'dot' and self._sounding == 'straight')
            colors = THEME_COLORS
            label.setStyleSheet(
                'QLabel { background: %s; color: %s; border: 1px solid %s; border-radius: 4px; }'
                % (colors['highlight'] if pressed else colors['surface'],
                   colors['highlight_text'] if pressed else colors['muted'],
                   colors['success'] if sounding else colors['accent'] if pressed else colors['border']))
        if 'commit' in self._roles:
            self.progress.setToolTip('确认键已按下')
        else:
            self.progress.setToolTip('字符确认进度；继续输入会重新计时。')

    def showResult(self, label, success=True):
        self.showMessage(('已输入：' if success else '无效码：') + str(label), success)

    def showMessage(self, message, success=True):
        """Display a complete status/error message without adding a prefix."""
        self._result_success = bool(success)
        self.result_label.setText(str(message))
        self._updateResultColor()
        self.result_timer.start()

    def clearResult(self):
        self._result_success = True
        self.result_label.setText('最近输入将显示在这里')
        self._updateResultColor()

    def _updateResultColor(self):
        color = THEME_COLORS['success' if self._result_success else 'danger']
        if not self.result_timer.isActive() and self.result_label._full_text == '最近输入将显示在这里':
            color = THEME_COLORS['muted']
        self.result_label.setStyleSheet('color: %s; background: transparent;' % color)

    def updateTheme(self):
        colors = THEME_COLORS
        self.setStyleSheet(
            'QFrame#inputFeedbackPanel { background: %s; border: 1px solid %s; border-radius: 7px; }'
            'QLabel#morseInput { background: transparent; color: %s; border: none; font-weight: bold; }'
            'QProgressBar { background: %s; border: none; border-radius: 2px; }'
            'QProgressBar::chunk { background: %s; border-radius: 2px; }'
            % (colors['input'], colors['border'], colors['accent'], colors['surface'], colors['accent']))
        self._updateIndicators()
        self._updateResultColor()


class KeyLabel(QLabel):
    """Paint changing colors without reparsing a stylesheet or rich text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._foreground = THEME_COLORS['text']
        self._prefix_color = THEME_COLORS['success']
        self._prefix_length = 0

    def setColors(self, foreground, prefix_color=None, prefix_length=0):
        state = (foreground, prefix_color or foreground, prefix_length)
        if state != (self._foreground, self._prefix_color, self._prefix_length):
            self._foreground, self._prefix_color, self._prefix_length = state
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(QColor(self._foreground))
        bounds = self.contentsRect().adjusted(self.margin(), self.margin(), -self.margin(), -self.margin())
        text = self.text()
        if self._prefix_length:
            metrics = self.fontMetrics()
            x = bounds.x() + (bounds.width() - metrics.horizontalAdvance(text)) / 2
            y = bounds.y() + (bounds.height() - metrics.height()) / 2 + metrics.ascent()
            prefix = text[:self._prefix_length]
            painter.setPen(QColor(self._prefix_color))
            painter.drawText(QPointF(x, y), prefix)
            painter.setPen(QColor(self._foreground))
            painter.drawText(QPointF(x + metrics.horizontalAdvance(prefix), y), text[self._prefix_length:])
        else:
            painter.drawText(bounds, self.alignment() | Qt.TextSingleLine, text)


class KeyCap(QFrame):
    """Read-only key with live prefix highlighting and action-owned labels."""

    def __init__(self, item, config, label=None, compact=False, parent=None):
        super().__init__(parent)
        self.item = item
        self.config = config
        self.label_override = label
        self.raw_code = item['code']
        self.code = morse(self.raw_code)
        self.is_available = True
        self._prefix_matches = True
        self.disabledchars = 0
        self.is_enabled = True
        self.toggled = False
        self._content_label = None
        self._appearance = None
        self.compact = compact
        self.scale = max(0.7, min(float(config.get('fontsizescale', 100)) / 100, 3))
        self.setObjectName('morseKey')
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.NoFocus)
        self.character = KeyLabel()
        self.character.setTextFormat(Qt.PlainText)
        self.character.setAlignment(Qt.AlignCenter)
        self.codeline = KeyLabel()
        self.codeline.setAlignment(Qt.AlignCenter)
        self.codeline.setTextFormat(Qt.PlainText)
        self.codeline.setText(self.code)
        self.codeline.setWordWrap(False)
        if compact == 'inline':
            self.character.setMargin(2)
            self.codeline.setMargin(2)
        content = QHBoxLayout(self) if compact == 'inline' else QVBoxLayout(self)
        content.setContentsMargins(5, 1, 5, 1) if compact else content.setContentsMargins(5, 3, 5, 4)
        content.setSpacing(1)
        content.addWidget(self.character)
        content.addWidget(self.codeline)
        self.setMinimumWidth(round((58 if compact else 51) * self.scale))
        self.setFixedHeight(round((26 if compact == 'inline' else 43 if compact else 51) * self.scale))
        font = QFont(QApplication.font())
        font.setPointSizeF((8.7 if self.compact else 9.5) * self.scale)
        font.setBold(True)
        self.character.setFont(font)
        code_font = QFont('Consolas')
        code_font.setPointSizeF((9.1 if self.compact else 10.0) * self.scale)
        self.codeline.setFont(code_font)
        self.updateView()

    def item_label(self):
        action = self.item.get('_action')
        label = action.getlabel() if action is not None else self.item.get('label', self.item.get('action', ''))
        return str(label) if label is not None else ''

    def updateView(self):
        label = self.label_override if self.label_override is not None else self.item_label()
        self.is_enabled = self._prefix_matches and self.is_available
        if (self.config.get('upperchars', False) and self.item.get('action') in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
              and len(self.item.get('action', '')) == 1 and len(label) == 1 and label in 'abcdefghijklmnopqrstuvwxyz'):
            label = label.upper()
        self._refreshAppearance()
        if label == self._content_label:
            return
        self._content_label = label
        self.character.setText(label)
        tooltip_label = (self.label_override if self.label_override is not None and not self.item['action'].startswith('MOUSE')
                         else self.item_label())
        self.setToolTip(tooltip_label + '\n' + self.code)
        self.refreshMetrics()

    def refreshMetrics(self):
        """Recalculate fixed key sizes even when a DPI change keeps the label."""
        for label in (self.character, self.codeline):
            # QLabel caches sizeHint. Embedded widgets need that cache reset
            # when the host changes screen without changing its QFont value.
            label.setMinimumHeight(0)
            QApplication.sendEvent(label, QEvent(QEvent.FontChange))
        # A seven-symbol code and translated key names must never be clipped.
        if self.compact == 'inline':
            minimum_width = self.codeline.sizeHint().width() + self.character.sizeHint().width() + 16
        else:
            minimum_width = max(self.codeline.sizeHint().width(), self.character.sizeHint().width()) + 12
        self.setMinimumWidth(max(round((58 if self.compact else 51) * self.scale), minimum_width))
        label_heights = [max(widget.sizeHint().height(), widget.fontMetrics().height() + 2 * widget.margin())
                         for widget in (self.character, self.codeline)]
        for widget, height in zip((self.character, self.codeline), label_heights):
            widget.setMinimumHeight(height)
        margins = self.layout().contentsMargins()
        padding_height = margins.top() + margins.bottom() + 2 * self.frameWidth()
        if self.compact == 'inline':
            content_height = max(label_heights) + padding_height
        else:
            content_height = sum(label_heights) + self.layout().spacing() + padding_height
        self.setFixedHeight(max(round((26 if self.compact == 'inline' else 43 if self.compact else 51) * self.scale),
                                content_height))

    def _refreshAppearance(self):
        colors = THEME_COLORS
        self.is_enabled = self._prefix_matches and self.is_available
        prefix_len = self.disabledchars if self.is_enabled else 0
        foreground = colors['highlight_text'] if self.toggled else colors['text'] if self.is_enabled else colors['disabled']
        code_color = colors['highlight_text'] if self.toggled else colors['accent'] if self.is_enabled else colors['disabled']
        background = colors['highlight'] if self.toggled else colors['surface'] if self.is_enabled else colors['background']
        border = colors['accent'] if self.toggled else colors['border'] if self.is_enabled else colors['surface']
        self.character.setColors(foreground)
        self.codeline.setColors(code_color, colors['success'], prefix_len)
        if self._appearance != (background, border):
            self._appearance = (background, border)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        background, border = self._appearance
        painter.setBrush(QColor(background))
        painter.setPen(QPen(QColor(border), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 6, 6)

    def enabled(self):
        return self.is_enabled

    def enable(self):
        self._prefix_matches = True
        self.updateView()

    def disable(self):
        self._prefix_matches = False
        self.updateView()

    def reset(self):
        self.disabledchars = 0
        self._prefix_matches = True
        self.updateView()

    def _advance(self, symbol):
        if not self._prefix_matches:
            return
        position = self.disabledchars
        if position < len(self.raw_code) and self.raw_code[position] == symbol:
            self.disabledchars += 1
        else:
            self._prefix_matches = False
        self._refreshAppearance()

    def Dit(self):
        self._advance('1')

    def Dah(self):
        self._advance('2')


class MouseShell(QFrame):
    """A recognizable mouse silhouette around the actual button mappings."""

    def paintEvent(self, event):
        if self.property('compactOverlay'):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(THEME_COLORS['border']), 1.4))
        painter.setBrush(QColor(THEME_COLORS['input']))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 38, 38)
        center = self.width() // 2
        painter.drawLine(center, 8, center, self.height() - 60)
        painter.setBrush(QColor(THEME_COLORS['border']))
        painter.drawRoundedRect(center - 3, 13, 6, 22, 3, 3)


class GuideViewport(QGraphicsView):
    """Scale the complete guide as one surface, keeping host controls readable."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setScene(QGraphicsScene(self))
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setFocusPolicy(Qt.NoFocus)
        self.auto_fit = True
        self.compact = False
        self.proxy = None

    def setBoard(self, board):
        self.board = board
        self.proxy = self.scene().addWidget(board)
        self.refreshLayout()

    def refreshLayout(self):
        if self.proxy is None:
            return
        self.board.ensurePolished()
        self.board.layout().invalidate()
        self.board.layout().activate()
        size = self.board.layout().sizeHint().expandedTo(self.board.layout().minimumSize())
        self.board.resize(size)
        self.board.layout().activate()
        # The proxy can initially clamp the board to its previous minimum.
        # Once the new child constraints are active, shrink both together.
        size = self.board.layout().sizeHint().expandedTo(self.board.layout().minimumSize())
        self.proxy.resize(size.width(), size.height())
        self.board.layout().activate()
        self.setSceneRect(self.proxy.boundingRect())
        self._fitBoard()

    def setAutoFit(self, value):
        self.auto_fit = bool(value)
        policy = Qt.ScrollBarAlwaysOff if self.auto_fit else Qt.ScrollBarAsNeeded
        self.setHorizontalScrollBarPolicy(policy)
        self.setVerticalScrollBarPolicy(policy)
        self._fitBoard()

    def _fitBoard(self):
        if self.proxy is None:
            return
        if self.compact:
            # fitInView reserves a margin. The overlay instead uses its exact
            # content bounds, so there is no invisible border around the keys.
            bounds = self.sceneRect()
            if bounds.width() > 0 and bounds.height() > 0:
                scale = min(self.viewport().width() / bounds.width(),
                            self.viewport().height() / bounds.height())
                self.setTransform(QTransform.fromScale(scale, scale))
        elif self.auto_fit:
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        else:
            self.resetTransform()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fitBoard()


class VirtualKeyboardView(QWidget):
    """All available desktop commands, arranged by physical position."""

    settingsRequested = pyqtSignal()
    changeLayoutSignal = pyqtSignal(str)
    mouseVisibilityChanged = pyqtSignal(bool)
    autoFitChanged = pyqtSignal(bool)
    compactModeChanged = pyqtSignal(bool)
    compactScaleChanged = pyqtSignal(float)

    DISPLAY_NAMES = {
        'ESCAPE': 'Esc', 'TAB': 'Tab', 'TABLEFT': 'Shift+Tab',
        'BACKSPACE': 'Backspace', 'CAPSLOCK': 'Caps Lock', 'ENTER': 'Enter',
        'SHIFT': 'Shift', 'CTRL': 'Ctrl', 'ALT': 'Alt', 'WINDOWS': 'Win',
        'SPACE': 'Space', 'APPLICATION': 'Menu', 'STARTMENU': 'Start Menu',
        'HOME': 'Home', 'END': 'End', 'INSERT': 'Insert', 'DELETE': 'Delete',
        'PAGEUP': 'PgUp', 'PAGEDOWN': 'PgDn',
        'UPARROW': '↑', 'LEFTARROW': '←', 'RIGHTARROW': '→', 'DOWNARROW': '↓',
    }

    def __init__(self, layout, config, parent=None):
        super().__init__(parent)
        self.layout = layout
        self.config = config
        self.crs = {}
        self.keystroke_crs_map = {}
        # Old user layouts can still contain removed prediction mappings.
        self._items = [item for item in layout['items'] if not item.get('emptyspace')
                       and item.get('action') != 'PREDICTION_SELECT']
        self._by_action = {}
        for item in self._items:
            self._by_action.setdefault(item['action'], []).append(item)
        self._held = ()
        self._locked = False
        self._prefix = ''
        self._section_titles = []
        self._mouse_visible = bool(config.get('show_mouse', False))
        self._auto_fit = bool(config.get('guide_auto_fit', True))
        self._compact_mode = False
        self._compact_scale = 1.0
        self._full_geometry = None
        self._drag_offset = None
        self._resize_edges = Qt.Edges()
        self._resize_origin = None
        self._screen = None
        self._screen_window = None
        self._screen_dirty = False
        self._screen_refreshing = False
        self._screen_refresh_timer = QTimer(self)
        self._screen_refresh_timer.setSingleShot(True)
        self._screen_refresh_timer.timeout.connect(self._refreshForScreenChange)
        app = QApplication.instance()
        app.screenAdded.connect(self._onScreenTopologyChanged)
        app.screenRemoved.connect(self._onScreenTopologyChanged)
        app.primaryScreenChanged.connect(self._onScreenTopologyChanged)
        self.setWindowTitle('摩斯输入 · 键盘与鼠标')
        self.setWindowIcon(QIcon(':/morse-writer.ico'))
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint |
                            Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(360, 280)
        self._build()
        self.updateTheme()
        available = QApplication.desktop().availableGeometry()
        self.resize(min(1280, available.width() - 32), min(780, available.height() - 64))
        self.adjustPosition()
        if config.get('guide_compact', False):
            self.outer_layout.activate()
            self.scroll_area._fitBoard()
            self.setCompactMode(True)
        self._bindWindowScreen()

    def _availableGeometry(self):
        return QApplication.desktop().availableGeometry(self)

    def _bindScreen(self, screen):
        if screen is self._screen:
            return
        signals = ('availableGeometryChanged', 'geometryChanged',
                   'logicalDotsPerInchChanged', 'physicalDotsPerInchChanged')
        if self._screen is not None and not sip.isdeleted(self._screen):
            for name in signals:
                getattr(self._screen, name).disconnect(self._scheduleScreenRefresh)
        self._screen = screen
        if screen is not None:
            for name in signals:
                getattr(screen, name).connect(self._scheduleScreenRefresh)

    def _bindWindowScreen(self):
        # setCompactMode recreates the native window. Never retain the previous
        # QWindow's subscription or call winId() while it is being destroyed.
        handle = self.windowHandle()
        if handle is not self._screen_window:
            if self._screen_window is not None and not sip.isdeleted(self._screen_window):
                self._screen_window.screenChanged.disconnect(self._onScreenChanged)
            self._screen_window = handle
            if handle is not None:
                handle.screenChanged.connect(self._onScreenChanged)
        screen = handle.screen() if handle is not None else None
        if screen not in QApplication.screens():
            screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        self._bindScreen(screen)

    def _onScreenChanged(self, screen):
        self._bindScreen(screen)
        self._scheduleScreenRefresh()

    def _onScreenTopologyChanged(self, *_args):
        self._bindWindowScreen()
        self._scheduleScreenRefresh()

    def _scheduleScreenRefresh(self, *_args):
        self._screen_dirty = True
        if not self._screen_refresh_timer.isActive() and not self._screen_refreshing:
            # Let Qt finish updating font DPI, native geometry and child layouts
            # before measuring the board. Coalesce the related screen signals.
            self._screen_refresh_timer.start(0)

    def _refreshForScreenChange(self):
        if self.isMinimized() or self._drag_offset is not None or self._resize_origin is not None:
            return  # Resume on restore or after the pointer is released.
        self._screen_refreshing = True
        self._screen_dirty = False
        try:
            for cap in self.crs.values():
                cap.refreshMetrics()
            self.scroll_area.refreshLayout()
            if self._compact_mode:
                self._fitCompactWindow()
            elif not self.isMaximized():
                available = self._availableGeometry()
                extra = self.frameGeometry().size() - self.size()
                self.resize(min(self.width(), max(1, available.width() - max(0, extra.width()))),
                            min(self.height(), max(1, available.height() - max(0, extra.height()))))
                frame = self.frameGeometry()
                self.move(max(available.left(), min(frame.left(), available.right() - frame.width() + 1)),
                          max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1)))
            self.outer_layout.activate()
            self.scroll_area._fitBoard()
            self.update()
        finally:
            self._screen_refreshing = False
        if self._screen_dirty:
            self._scheduleScreenRefresh()

    def event(self, event):
        result = super().event(event)
        if hasattr(self, '_screen_refresh_timer') and hasattr(self, 'scroll_area'):
            if event.type() in (QEvent.Show, QEvent.WinIdChange):
                self._bindWindowScreen()
                self._scheduleScreenRefresh()
            elif event.type() in (QEvent.FontChange, QEvent.ApplicationFontChange, QEvent.WindowStateChange):
                self._scheduleScreenRefresh()
        return result

    def adjustPosition(self):
        available = self._availableGeometry()
        frame = self.frameSize()
        offset_x = int(float(self.config.get('winposx', 10)))
        offset_y = int(float(self.config.get('winposy', 10)))
        max_x = available.x() + max(0, available.width() - frame.width())
        max_y = available.y() + max(0, available.height() - frame.height())
        position_x = (max_x - offset_x if self.config.get('winxaxis', 'left') == 'right'
                      else available.x() + offset_x)
        position_y = (max_y - offset_y if self.config.get('winyaxis', 'top') == 'bottom'
                      else available.y() + offset_y)
        self.move(max(available.x(), min(position_x, max_x)),
                  max(available.y(), min(position_y, max_y)))

    def _title(self, title, subtitle=None):
        label = QLabel(title)
        font = QFont(QApplication.font())
        font.setBold(True)
        font.setPointSizeF(10.5)
        label.setFont(font)
        self._section_titles.append(label)
        if subtitle:
            row = QHBoxLayout()
            row.addWidget(label)
            detail = QLabel(subtitle)
            detail.setObjectName('guideHint')
            row.addWidget(detail)
            row.addStretch()
            return row
        return label

    def _cap(self, action, label=None, compact=False, item=None):
        if item is None:
            item = next((entry for entry in self._by_action.get(action, [])
                         if entry['code'] not in self.crs), None)
        if item is None or item['code'] in self.crs:
            return None
        cap = KeyCap(item, self.config, label if label is not None else self.DISPLAY_NAMES.get(action), compact)
        self.crs[item['code']] = cap
        self.keystroke_crs_map[action] = cap
        return cap

    def _row(self, actions, compact=False):
        row = QHBoxLayout()
        row.setSpacing(5)
        row.setContentsMargins(0, 0, 0, 0)
        for entry in actions:
            action, width = entry if isinstance(entry, tuple) else (entry, 10)
            if action is None:
                row.addStretch(width)
                continue
            cap = self._cap(action, compact=compact)
            if cap is not None:
                row.addWidget(cap, width)
        return row

    def _build(self):
        outer = QVBoxLayout(self)
        self.outer_layout = outer
        outer.setContentsMargins(16, 12, 16, 8)
        outer.setSpacing(10)
        self.header_widget = QWidget()
        self.header = QGridLayout(self.header_widget)
        self.header.setContentsMargins(0, 0, 0, 0)
        self.header.setHorizontalSpacing(10)
        self.header.setVerticalSpacing(4)
        self.heading = QLabel('键盘与鼠标')
        title_font = QFont(QApplication.font())
        title_font.setPointSizeF(16)
        title_font.setBold(True)
        self.heading.setFont(title_font)
        self.subtitle = QLabel('照着键位输入摩斯码，匹配的按键会自动亮起。')
        self.subtitle.setObjectName('guideHint')
        self.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.input_feedback = InputFeedbackPanel()
        self.input_label = self.input_feedback.code_label
        self.settings_button = QPushButton('返回设置')
        self.settings_button.setToolTip('暂停输入并返回设置（Ctrl + Shift + P）')
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        self.view_options = QWidget()
        options = QHBoxLayout(self.view_options)
        options.setContentsMargins(0, 0, 0, 0)
        options.setSpacing(12)
        self.mouse_checkbox = QCheckBox('鼠标')
        self.mouse_checkbox.setChecked(self._mouse_visible)
        self.mouse_checkbox.setToolTip('显示鼠标按键和移动方向的对照表。')
        self.mouse_checkbox.toggled.connect(self.setMouseVisible)
        options.addWidget(self.mouse_checkbox)
        self.auto_fit_checkbox = QCheckBox('适应窗口')
        self.auto_fit_checkbox.setChecked(self._auto_fit)
        self.auto_fit_checkbox.setToolTip('缩放完整对照表；关闭后按设置字号显示，并可滚动查看。')
        self.auto_fit_checkbox.toggled.connect(self.setAutoFit)
        options.addWidget(self.auto_fit_checkbox)
        self.compact_checkbox = QCheckBox('精简显示')
        self.compact_checkbox.setToolTip('只显示透明键位板；拖动按键可移动，右键可返回完整显示。')
        self.compact_checkbox.toggled.connect(self.setCompactMode)
        options.addWidget(self.compact_checkbox)
        self._compact_header = None
        self._set_compact_header(self.width() < 760)
        outer.addWidget(self.header_widget)
        outer.addWidget(self.input_feedback)

        self.scroll_area = GuideViewport()
        self.scroll_area.viewport().setMouseTracking(True)
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.setContextMenuPolicy(Qt.CustomContextMenu)
        self.scroll_area.customContextMenuRequested.connect(self._showContextMenu)
        self.chart_widget = QWidget()
        self.chart_widget.setObjectName('guideBoard')
        body = QHBoxLayout(self.chart_widget)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        keyboard = QVBoxLayout()
        keyboard.setSpacing(6)
        keyboard.addLayout(self._title('键盘', '字母、数字与常用按键'))
        keyboard.addLayout(self._row(['ESCAPE', (None, 4)] + ['F' + str(i) for i in range(1, 13)]))
        keyboard.addSpacing(3)
        keyboard.addLayout(self._row([
            'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE', 'ZERO',
            'MINUS', 'EQUALS', ('BACKSPACE', 20),
        ]))
        keyboard.addLayout(self._row([('TAB', 15)] + list('QWERTYUIOP') + [('BSLASH', 15)]))
        keyboard.addLayout(self._row([('CAPSLOCK', 18)] + list('ASDFGHJKL') +
                                     ['SEMICOLON', 'SINGLEQUOTE', ('ENTER', 20)]))
        keyboard.addLayout(self._row([('SHIFT', 22)] + list('ZXCVBNM') +
                                     ['COMMA', 'DOT', 'FSLASH', ('TABLEFT', 20)]))
        keyboard.addLayout(self._row([
            ('CTRL', 15), ('WINDOWS', 15), ('ALT', 15), ('SPACE', 60),
            ('APPLICATION', 23),
        ]))
        keyboard.addSpacing(5)
        extras = QHBoxLayout()
        extras.setSpacing(14)
        symbols = QVBoxLayout()
        symbols.setSpacing(5)
        symbols.addWidget(self._title('符号'))
        for row in (
            ['EXCLAMATION', 'AT', 'HASH', 'DOLLAR', 'PERCENT', 'CIRCONFLEX', 'AMPERSAND', 'STAR', 'PLUS'],
            ['QUESTION', 'COLON', 'DOUBLEQUOTE', 'OPENBRACKET', 'CLOSEBRACKET', 'LESSTHAN', 'MORETHAN', 'UNDERSCORE'],
        ):
            symbols.addLayout(self._row(row, compact=True))
        tools = QHBoxLayout()
        tools.setSpacing(5)
        for action in ('STARTMENU', 'REPEATMODE', 'SOUND'):
            cap = self._cap(action, compact=True)
            if cap:
                tools.addWidget(cap)
        tools.addStretch(2)
        symbols.addLayout(tools)
        symbols.addStretch()
        extras.addLayout(symbols, 3)
        navigation = QVBoxLayout()
        navigation.setSpacing(5)
        navigation.addWidget(self._title('导航'))
        nav_grid = QGridLayout()
        nav_grid.setSpacing(4)
        for action, row, column in (
            ('INSERT', 0, 0), ('HOME', 0, 1), ('PAGEUP', 0, 2),
            ('DELETE', 1, 0), ('END', 1, 1), ('PAGEDOWN', 1, 2),
            ('UPARROW', 2, 1), ('LEFTARROW', 3, 0), ('DOWNARROW', 3, 1), ('RIGHTARROW', 3, 2),
        ):
            cap = self._cap(action, compact=True)
            if cap:
                nav_grid.addWidget(cap, row, column)
        navigation.addLayout(nav_grid)
        extras.addLayout(navigation, 1)

        symbol_tools = QVBoxLayout()
        symbol_tools.setSpacing(5)
        symbol_tools.addLayout(extras)
        keyboard.addLayout(symbol_tools)
        body.addLayout(keyboard, 3)
        self.mouse_panel = QWidget()
        self.mouse_panel.setLayout(self._mouse_panel())
        self.mouse_panel.layout().setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.mouse_panel, 1)
        self.mouse_panel.setVisible(self._mouse_visible)
        remaining = [item for item in self._items if item['code'] not in self.crs]
        if remaining:
            keyboard.addWidget(self._title('其他操作'))
            grid = QGridLayout()
            grid.setSpacing(5)
            for index, item in enumerate(remaining):
                grid.addWidget(self._cap(item['action'], compact=True, item=item), index // 3, index % 3)
            keyboard.addLayout(grid)
        keyboard.addStretch()
        self._annotations = [label for label in self.chart_widget.findChildren(QLabel)
                             if not isinstance(label, KeyLabel)]
        self._annotation_visibility = {}
        self.scroll_area.setBoard(self.chart_widget)
        self.scroll_area.setAutoFit(self._auto_fit)
        outer.addWidget(self.scroll_area, 1)
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        outer.addWidget(self.status_bar)
        self.setOutputState((), False)

    def _mouse_panel(self):
        panel = QVBoxLayout()
        panel.setSpacing(7)
        panel.addLayout(self._title('鼠标', '按键与八向移动'))
        shell = MouseShell()
        self.mouse_shell = shell
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(15, 25, 15, 12)
        shell_layout.setSpacing(5)
        buttons = QHBoxLayout()
        buttons.setSpacing(14)
        for suffix, title in [('LEFT', '左键'), ('RIGHT', '右键')]:
            half = QVBoxLayout()
            half.setSpacing(4)
            label = QLabel(title)
            label.setAlignment(Qt.AlignCenter)
            label.setMargin(2)
            half.addWidget(label)
            for prefix, label in [('MOUSECLICK', '单击'), ('MOUSEDBLCLICK', '双击'), ('MOUSECLKHLD', '按住')]:
                cap = self._cap(prefix + suffix, label=label, compact='inline')
                if cap:
                    half.addWidget(cap)
            buttons.addLayout(half, 1)
        shell_layout.addLayout(buttons)
        release = self._cap('MOUSERELEASEHOLD', label='松开鼠标', compact='inline')
        if release:
            shell_layout.addWidget(release)
        panel.addWidget(shell)
        panel.addWidget(self._title('移动距离'))
        directions = QGridLayout()
        directions.setSpacing(5)
        for suffix, arrow, title, row, column in (
            ('UPLEFT', '↖', '左上', 0, 0), ('UP', '↑', '向上', 0, 1), ('UPRIGHT', '↗', '右上', 0, 2),
            ('LEFT', '←', '向左', 1, 0), ('RIGHT', '→', '向右', 1, 2),
            ('DOWNLEFT', '↙', '左下', 2, 0), ('DOWN', '↓', '向下', 2, 1), ('DOWNRIGHT', '↘', '右下', 2, 2),
        ):
            cell = QVBoxLayout()
            cell.setSpacing(3)
            heading = QLabel(arrow + ' ' + title)
            heading.setAlignment(Qt.AlignCenter)
            heading.setMargin(2)
            cell.addWidget(heading)
            for distance in (5, 40, 250):
                cap = self._cap('MOUSE' + suffix + str(distance), label=str(distance), compact='inline')
                if cap:
                    cell.addWidget(cap)
            directions.addLayout(cell, row, column)
        legend = QLabel('移动\n单位：像素')
        legend.setObjectName('guideHint')
        legend.setAlignment(Qt.AlignCenter)
        directions.addWidget(legend, 1, 1)
        panel.addLayout(directions)
        panel.addStretch()
        return panel

    def setAvailableLayouts(self, layouts, active):
        # Kept for the host's shared view interface; desktop commands stay together.
        pass

    def _set_compact_header(self, compact):
        if compact == self._compact_header:
            return
        self._compact_header = compact
        for widget in (self.heading, self.subtitle, self.settings_button, self.view_options):
            self.header.removeWidget(widget)
        for column in range(4):
            self.header.setColumnStretch(column, 0)
            self.header.setColumnMinimumWidth(column, 0)
        self.header.addWidget(self.heading, 0, 0)
        self.header.setColumnStretch(0, 1)
        if compact:
            self.subtitle.hide()
            self.header.addWidget(self.settings_button, 0, 1)
            self.header.addWidget(self.view_options, 1, 0, 1, 2)
        else:
            self.subtitle.show()
            self.header.addWidget(self.subtitle, 1, 0, 1, 2)
            self.header.addWidget(self.view_options, 0, 1)
            self.header.addWidget(self.settings_button, 0, 2, 2, 1)

    def resizeEvent(self, event):
        self._set_compact_header(event.size().width() < 760)
        super().resizeEvent(event)

    def isCompactMode(self):
        return self._compact_mode

    def setCompactMode(self, value):
        """Switch presentation without replacing the board or input session."""
        value = bool(value)
        self.config['guide_compact'] = value
        if value == self._compact_mode:
            return
        was_visible, was_minimized = self.isVisible(), self.isMinimized()
        had_native_window = self.testAttribute(Qt.WA_WState_Created)
        if value:
            saved_scale = self.config.get('guide_compact_scale')
            self._compact_scale = (min(3.0, saved_scale)
                                   if isinstance(saved_scale, (float, int)) and
                                   isfinite(saved_scale) and saved_scale > 0 else
                                   self.scroll_area.transform().m11())
            self._full_geometry = QRect(self.normalGeometry() if self.isMaximized() or was_minimized else self.geometry())
        self._compact_mode = value
        self._drag_offset = None
        self._resize_edges = Qt.Edges()
        self._resize_origin = None
        self.compact_checkbox.blockSignals(True)
        self.compact_checkbox.setChecked(value)
        self.compact_checkbox.blockSignals(False)

        # Changing native flags can recreate the HWND. Keep the same Qt widget,
        # graphics proxy ownership, and signal connections throughout.
        flags = self.windowFlags()
        if value:
            flags |= Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
        else:
            flags &= ~(Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setWindowFlags(flags)
        if had_native_window and QApplication.platformName() == 'windows':
            # Qt 5 keeps the old framed backing store when toggling translucency
            # after show. Its dirty rectangle can then exceed the layered HWND,
            # making UpdateLayeredWindowIndirect fail and the whole guide vanish.
            # Release native resources only; retain the widget, board and signals.
            self.destroy()
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, value)
        self.setAttribute(Qt.WA_NoSystemBackground, value)
        self.setFocusPolicy(Qt.NoFocus if value else Qt.StrongFocus)
        self.setMinimumSize(1, 1) if value else self.setMinimumSize(360, 280)
        self.header_widget.setVisible(not value)
        self.input_feedback.setVisible(not value)
        self.status_bar.setVisible(not value)
        self.outer_layout.setContentsMargins(0, 0, 0, 0) if value else self.outer_layout.setContentsMargins(16, 12, 16, 8)
        self.outer_layout.setSpacing(0 if value else 10)
        self.scroll_area.compact = value
        self.scroll_area.setAutoFit(value or self._auto_fit)
        self.mouse_shell.setProperty('compactOverlay', value)
        if value:
            self._annotation_visibility = {label: not label.isHidden() for label in self._annotations}
        for label, was_shown in self._annotation_visibility.items():
            label.setVisible(was_shown and not value)
        self.scroll_area.viewport().setCursor(Qt.SizeAllCursor if value else Qt.ArrowCursor)
        self.updateTheme()
        if not was_minimized:
            self.setWindowState(Qt.WindowNoState)
        if value:
            self._fitCompactWindow()
        elif self._full_geometry is not None:
            self.setGeometry(self._full_geometry)
        self.outer_layout.activate()
        if was_visible:
            if was_minimized:
                show_guide_without_activation(self, keep_minimized=True)
            else:
                show_guide_without_activation(self)
        self.compactModeChanged.emit(value)

    def compactScale(self):
        return self._compact_scale

    def _minimumCompactScale(self):
        heights = [label.fontMetrics().height() for cap in self.crs.values()
                   for label in (cap.character, cap.codeline)]
        return min(1.0, 9.0 / max(1, min(heights, default=9)))

    def setCompactScale(self, scale, *, persist=True):
        scale = float(scale)
        if not isfinite(scale) or scale <= 0:
            raise ValueError('缩放比例必须是正数。')
        self._compact_scale = max(self._minimumCompactScale(), min(3.0, scale))
        self.config['guide_compact_scale'] = self._compact_scale
        self._fitCompactWindow()
        if persist:
            self.compactScaleChanged.emit(self._compact_scale)

    def resetCompactScale(self):
        self.setCompactScale(1.0)

    def _resizeEdges(self, position):
        bounds = self.scroll_area.viewport().rect()
        band = 6
        edges = Qt.Edges()
        if position.x() <= bounds.left() + band:
            edges |= Qt.LeftEdge
        elif position.x() >= bounds.right() - band:
            edges |= Qt.RightEdge
        if position.y() <= bounds.top() + band:
            edges |= Qt.TopEdge
        elif position.y() >= bounds.bottom() - band:
            edges |= Qt.BottomEdge
        return edges

    def _resizeCursor(self, edges):
        horizontal = bool(edges & (Qt.LeftEdge | Qt.RightEdge))
        vertical = bool(edges & (Qt.TopEdge | Qt.BottomEdge))
        if horizontal and vertical:
            return (Qt.SizeFDiagCursor if bool(edges & Qt.LeftEdge) == bool(edges & Qt.TopEdge)
                    else Qt.SizeBDiagCursor)
        return Qt.SizeHorCursor if horizontal else Qt.SizeVerCursor if vertical else Qt.SizeAllCursor

    def _resizeFromPointer(self, position):
        origin, pointer = self._resize_origin
        edges = self._resize_edges
        delta = position - pointer
        width_delta = (-delta.x() if edges & Qt.LeftEdge else delta.x())
        height_delta = (-delta.y() if edges & Qt.TopEdge else delta.y())
        width_from_height = height_delta * origin.width() / max(1, origin.height())
        if not edges & (Qt.LeftEdge | Qt.RightEdge):
            width_delta = width_from_height
        elif edges & (Qt.TopEdge | Qt.BottomEdge) and abs(width_from_height) > abs(width_delta):
            width_delta = width_from_height
        bounds = self.scroll_area.sceneRect()
        scale = max(0.001, (origin.width() + width_delta) / max(1, bounds.width()))
        self.setCompactScale(scale, persist=False)
        x = origin.right() + 1 - self.width() if edges & Qt.LeftEdge else origin.x()
        y = origin.bottom() + 1 - self.height() if edges & Qt.TopEdge else origin.y()
        self._moveInsideScreen(QPoint(x, y), self._availableGeometry())

    def _fitCompactWindow(self):
        """Make the actual top-level rectangle match the complete board."""
        if not self._compact_mode:
            return
        self.scroll_area.refreshLayout()
        bounds = self.scroll_area.sceneRect()
        available = self._availableGeometry()
        # Crop the currently rendered keys rather than enlarging them when the
        # surrounding controls disappear. Optional mouse keys may only reduce
        # this scale as needed to stay within the available screen.
        scale = min(self._compact_scale,
                    available.width() / max(1, bounds.width()),
                    available.height() / max(1, bounds.height()))
        self.resize(min(available.width(), ceil(bounds.width() * scale)),
                    min(available.height(), ceil(bounds.height() * scale)))
        self.outer_layout.activate()
        self.scroll_area._fitBoard()
        self._moveInsideScreen(self.pos(), available)

    def _moveInsideScreen(self, position, available=None):
        if available is None:
            screen = QApplication.screenAt(position + self.rect().center())
            available = screen.availableGeometry() if screen else QApplication.desktop().availableGeometry(self)
        self.move(max(available.left(), min(position.x(), available.right() - self.width() + 1)),
                  max(available.top(), min(position.y(), available.bottom() - self.height() + 1)))

    def eventFilter(self, watched, event):
        if self._compact_mode and watched is self.scroll_area.viewport():
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._resize_edges = self._resizeEdges(event.pos())
                if self._resize_edges:
                    self._resize_origin = (QRect(self.geometry()), event.globalPos())
                else:
                    self._drag_offset = event.globalPos() - self.pos()
                return True
            if event.type() == QEvent.MouseMove:
                if event.buttons() & Qt.LeftButton:
                    if self._resize_origin is not None:
                        self._resizeFromPointer(event.globalPos())
                        return True
                    if self._drag_offset is not None:
                        self._moveInsideScreen(event.globalPos() - self._drag_offset)
                        return True
                if self._resize_origin is not None:
                    self.compactScaleChanged.emit(self._compact_scale)
                self._resize_origin = None
                self._resize_edges = Qt.Edges()
                self._drag_offset = None
                if self._screen_dirty:
                    self._scheduleScreenRefresh()
                watched.setCursor(self._resizeCursor(self._resizeEdges(event.pos())))
                return True  # Keep QGraphicsView from replacing the resize cursor.
            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                if self._resize_origin is not None:
                    self._resizeFromPointer(event.globalPos())
                    self.compactScaleChanged.emit(self._compact_scale)
                self._resize_origin = None
                self._resize_edges = Qt.Edges()
                self._drag_offset = None
                if self._screen_dirty:
                    self._scheduleScreenRefresh()
                return True
        return super().eventFilter(watched, event)

    def createViewMenu(self):
        """Provide an exit from the frameless view without a permanent toolbar."""
        menu = QMenu(self)
        display_action = menu.addAction('完整显示' if self._compact_mode else '精简显示')
        target_mode = not self._compact_mode
        display_action.triggered.connect(lambda checked=False: self.setCompactMode(target_mode))
        if self._compact_mode:
            zoom = menu.addMenu('调整大小')
            for text, name, callback in (
                    ('放大', 'compactZoomIn', lambda: self.setCompactScale(self.compactScale() * 1.15)),
                    ('缩小', 'compactZoomOut', lambda: self.setCompactScale(self.compactScale() / 1.15)),
                    ('默认大小', 'compactZoomReset', self.resetCompactScale)):
                action = zoom.addAction(text)
                action.setObjectName(name)
                action.triggered.connect(callback)
        mouse_action = menu.addAction('显示鼠标')
        mouse_action.setCheckable(True)
        mouse_action.setChecked(self._mouse_visible)
        mouse_action.toggled.connect(self.setMouseVisible)
        menu.addSeparator()
        menu.addAction('返回设置', self.settingsRequested.emit)
        menu.addAction('隐藏码表', self.hide)
        return menu

    def _showContextMenu(self, position):
        menu = self.createViewMenu()
        menu.exec_(self.scroll_area.viewport().mapToGlobal(position))
        menu.deleteLater()

    def setMouseVisible(self, value):
        value = bool(value)
        changed = value != self._mouse_visible
        self._mouse_visible = value
        self.config['show_mouse'] = value
        self.mouse_checkbox.blockSignals(True)
        self.mouse_checkbox.setChecked(value)
        self.mouse_checkbox.blockSignals(False)
        self.mouse_panel.setVisible(value)
        self.scroll_area.refreshLayout()
        self._fitCompactWindow()
        if changed:
            self.mouseVisibilityChanged.emit(value)

    def setAutoFit(self, value):
        value = bool(value)
        changed = value != self._auto_fit
        self._auto_fit = value
        self.config['guide_auto_fit'] = value
        self.auto_fit_checkbox.blockSignals(True)
        self.auto_fit_checkbox.setChecked(value)
        self.auto_fit_checkbox.blockSignals(False)
        self.scroll_area.setAutoFit(value or self._compact_mode)
        if changed:
            self.autoFitChanged.emit(value)

    def setOutputState(self, held_modifiers, locked):
        self._held = tuple(held_modifiers)
        self._locked = locked
        held = set(self._held)
        names = {'ctrl': 'Ctrl', 'shift': 'Shift', 'alt': 'Alt', 'windows': 'Win'}
        parts = ['已暂停' if self.config.get('off', False) else '输入中',
                 '提示音开' if self.config.get('withsound', False) else '提示音关']
        if locked:
            parts.append('修饰键已锁定')
        if held:
            parts.append('按住：' + ' + '.join(names.get(key, key) for key in self._held))
        self.status_bar.showMessage(' · '.join(parts))
        for cap in self.crs.values():
            action = cap.item.get('_action')
            key = getattr(action, 'key', None)
            modifier = getattr(action, 'toggle_action', False)
            cap.toggled = ((modifier and key in held) or
                           (cap.item['action'] == 'REPEATMODE' and locked) or
                           (cap.item['action'] == 'SOUND' and self.config.get('withsound', False)))
            cap.updateView()

    def reset(self):
        self._prefix = ''
        self.input_label.setText('等待输入')
        self.input_feedback.setInputFeedback()
        for cap in self.crs.values():
            cap.reset()

    def setInputFeedback(self, held_roles=(), progress=0.0, sounding=None):
        """Update held dot/dash/straight roles and 0–1 commit progress only."""
        self.input_feedback.setInputFeedback(held_roles, progress, sounding)

    def showResult(self, label, success=True):
        """Show recent output independently of reset and subsequent input."""
        self.input_feedback.showResult(label, success)

    def showMessage(self, message, success=True):
        """Show a complete diagnostic/status message verbatim."""
        self.input_feedback.showMessage(message, success)

    def _advance(self, symbol):
        self._prefix += symbol
        self.input_label.setText(morse(self._prefix))
        for cap in self.crs.values():
            cap.Dit() if symbol == '1' else cap.Dah()

    def Dit(self):
        self._advance('1')

    def Dah(self):
        self._advance('2')

    def updateTheme(self):
        colors = THEME_COLORS
        background = 'transparent' if self._compact_mode else colors['background']
        self.setStyleSheet(
            'VirtualKeyboardView, QGraphicsView { background: %s; }'
            'QLabel#guideHint { color: %s; }'
            % (background, colors['muted'])
        )
        self.scroll_area.viewport().setAutoFillBackground(not self._compact_mode)
        self.scroll_area.viewport().setStyleSheet('background: %s;' % background)
        self.input_feedback.updateTheme()
        self.chart_widget.setStyleSheet(
            'QWidget#guideBoard { background: %s; } QLabel#guideHint { color: %s; }'
            % (background, colors['muted']))
        for cap in self.crs.values():
            cap.updateView()
        self.scroll_area.refreshLayout()
        self._fitCompactWindow()
        self.update()

    def closeEvent(self, event):
        event.ignore()
        # The application's tray remains available; closing this guide does
        # not alter the running input session. Minimize retains Qt's standard
        # taskbar behavior for this independent Qt.Window.
        self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_P and event.modifiers() & Qt.ControlModifier and event.modifiers() & Qt.ShiftModifier:
            self.settingsRequested.emit()
        else:
            super().keyPressEvent(event)

    def updateSoundSupport(self):
        return True
