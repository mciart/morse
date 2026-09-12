"""A single, spatial Morse guide for keyboard and mouse actions."""

from html import escape

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QStatusBar, QVBoxLayout, QWidget,
)

from ui_theme import THEME_COLORS


def morse(code):
    return str(code).replace('1', '•').replace('2', '–')


class KeyCap(QFrame):
    """Read-only key with live prefix highlighting and action-owned labels."""

    def __init__(self, item, config, label=None, compact=False, parent=None):
        super().__init__(parent)
        self.item = item
        self.config = config
        self.label_override = label
        self.raw_code = item['code']
        self.code = morse(self.raw_code)
        self.disabledchars = 0
        self.is_enabled = True
        self.toggled = False
        self.compact = compact
        self.scale = max(0.7, min(float(config.get('fontsizescale', 100)) / 100, 3))
        self.setObjectName('morseKey')
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.NoFocus)
        self.character = QLabel()
        self.character.setTextFormat(Qt.PlainText)
        self.character.setAlignment(Qt.AlignCenter)
        self.codeline = QLabel()
        self.codeline.setAlignment(Qt.AlignCenter)
        self.codeline.setTextFormat(Qt.RichText)
        self.codeline.setWordWrap(False)
        content = QHBoxLayout(self) if compact == 'inline' else QVBoxLayout(self)
        content.setContentsMargins(5, 1, 5, 1) if compact else content.setContentsMargins(5, 3, 5, 4)
        content.setSpacing(1)
        content.addWidget(self.character)
        content.addWidget(self.codeline)
        self.setMinimumWidth(round((58 if compact else 51) * self.scale))
        self.setFixedHeight(round((26 if compact == 'inline' else 43 if compact else 51) * self.scale))
        self.updateView()

    def item_label(self):
        action = self.item.get('_action')
        label = action.getlabel() if action is not None else self.item.get('label', self.item.get('action', ''))
        if not label and self.item.get('action') == 'PREDICTION_SELECT':
            return '候选 ' + str(self.item.get('target', 0) + 1)
        return str(label)

    def updateView(self):
        colors = THEME_COLORS
        label = self.label_override if self.label_override is not None else self.item_label()
        if self.config.get('upperchars', False):
            label = label.upper()
        font = QFont(QApplication.font())
        font.setPointSizeF((8.7 if self.compact else 9.5) * self.scale)
        font.setBold(True)
        self.character.setFont(font)
        self.character.setText(label)
        code_font = QFont('Consolas')
        code_font.setPointSizeF((9.1 if self.compact else 10.0) * self.scale)
        self.codeline.setFont(code_font)
        prefix_len = self.disabledchars if self.is_enabled else 0
        foreground = colors['highlight_text'] if self.toggled else colors['text'] if self.is_enabled else colors['disabled']
        code_color = colors['highlight_text'] if self.toggled else colors['accent'] if self.is_enabled else colors['disabled']
        background = colors['highlight'] if self.toggled else colors['surface'] if self.is_enabled else colors['background']
        border = colors['accent'] if self.toggled else colors['border'] if self.is_enabled else colors['surface']
        self.setStyleSheet(
            'QFrame#morseKey { background: %s; border: 1px solid %s; border-radius: 6px; }'
            'QFrame#morseKey QLabel { background: transparent; border: none; color: %s; }'
            % (background, border, foreground)
        )
        self.codeline.setText(
            '<span style="color:%s">%s</span><span style="color:%s">%s</span>'
            % (colors['success'], escape(self.code[:prefix_len]), code_color, escape(self.code[prefix_len:]))
        )
        self.setToolTip(self.item_label() + '\n' + self.code)
        # A seven-symbol code and translated key names must never be clipped.
        if self.compact == 'inline':
            minimum_width = self.codeline.sizeHint().width() + self.character.sizeHint().width() + 16
        else:
            minimum_width = max(self.codeline.sizeHint().width(), self.character.sizeHint().width()) + 12
        self.setMinimumWidth(max(round((58 if self.compact else 51) * self.scale), minimum_width))

    def enabled(self):
        return self.is_enabled

    def enable(self):
        self.is_enabled = True
        self.updateView()

    def disable(self):
        self.is_enabled = False
        self.updateView()

    def reset(self):
        self.disabledchars = 0
        self.is_enabled = True
        self.updateView()

    def _advance(self, symbol):
        if self.is_enabled:
            position = self.disabledchars
            if position < len(self.raw_code) and self.raw_code[position] == symbol:
                self.disabledchars += 1
            else:
                self.is_enabled = False
            self.updateView()

    def Dit(self):
        self._advance('1')

    def Dah(self):
        self._advance('2')


class MouseShell(QFrame):
    """A recognizable mouse silhouette around the actual button mappings."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(THEME_COLORS['border']), 1.4))
        painter.setBrush(QColor(THEME_COLORS['input']))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 38, 38)
        center = self.width() // 2
        painter.drawLine(center, 8, center, self.height() - 60)
        painter.setBrush(QColor(THEME_COLORS['border']))
        painter.drawRoundedRect(center - 3, 13, 6, 22, 3, 3)


class VirtualKeyboardView(QWidget):
    """All available desktop commands, arranged by physical position."""

    settingsRequested = pyqtSignal()
    changeLayoutSignal = pyqtSignal(str)

    DISPLAY_NAMES = {
        'ESCAPE': '退出', 'TAB': '制表', 'TABLEFT': '反向制表',
        'SHIFT': 'Shift', 'CTRL': 'Ctrl', 'ALT': 'Alt', 'WINDOWS': 'Win',
        'UPARROW': '↑', 'LEFTARROW': '←', 'RIGHTARROW': '→', 'DOWNARROW': '↓',
    }

    def __init__(self, layout, config, parent=None):
        super().__init__(parent)
        self.layout = layout
        self.config = config
        self.crs = {}
        self.keystroke_crs_map = {}
        self._items = [item for item in layout['items'] if not item.get('emptyspace')]
        self._by_action = {}
        for item in self._items:
            self._by_action.setdefault(item['action'], []).append(item)
        self._held = ()
        self._locked = False
        self._prefix = ''
        self._section_titles = []
        self.setWindowTitle('摩斯输入 · 键盘与鼠标')
        self.setWindowIcon(QIcon(':/morse-writer.ico'))
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint |
                            Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.StrongFocus)
        self._build()
        self.updateTheme()
        available = QApplication.desktop().availableGeometry()
        self.resize(min(1280, available.width() - 32), min(780, available.height() - 64))
        self.adjustPosition()

    def adjustPosition(self):
        available = QApplication.desktop().availableGeometry(self)
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
        outer.setContentsMargins(16, 12, 16, 8)
        outer.setSpacing(10)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel('键盘与鼠标')
        title_font = QFont(QApplication.font())
        title_font.setPointSizeF(16)
        title_font.setBold(True)
        title.setFont(title_font)
        heading.addWidget(title)
        subtitle = QLabel('照着键位输入摩斯码，匹配的按键会自动亮起。')
        subtitle.setObjectName('guideHint')
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)
        self.input_label = QLabel('等待输入')
        self.input_label.setAlignment(Qt.AlignCenter)
        self.input_label.setMinimumWidth(150)
        self.input_label.setObjectName('morseInput')
        header.addWidget(self.input_label)
        settings = QPushButton('返回设置')
        settings.setToolTip('暂停输入并返回设置（Ctrl + Shift + P）')
        settings.clicked.connect(self.settingsRequested.emit)
        header.addWidget(settings)
        outer.addLayout(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.chart_widget = QWidget()
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
            ('APPLICATION', 23), ('STARTMENU', 23),
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
        predictions = [item for item in self._items if item['action'] == 'PREDICTION_SELECT']
        if predictions:
            symbols.addSpacing(8)
            symbols.addWidget(self._title('词语候选'))
            prediction_row = QHBoxLayout()
            prediction_row.setSpacing(5)
            for item in sorted(predictions, key=lambda entry: entry.get('target', 0)):
                cap = self._cap('PREDICTION_SELECT', compact=True, item=item)
                prediction_row.addWidget(cap, 1)
            symbols.addLayout(prediction_row)
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
        keyboard.addStretch()
        body.addLayout(keyboard, 3)
        mouse = self._mouse_panel()
        body.addLayout(mouse, 1)
        self.scroll_area.setWidget(self.chart_widget)
        outer.addWidget(self.scroll_area, 1)
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        outer.addWidget(self.status_bar)
        self.setOutputState((), False)

    def _mouse_panel(self):
        panel = QVBoxLayout()
        panel.setSpacing(7)
        panel.addLayout(self._title('鼠标', '按键与八向移动'))
        shell = MouseShell()
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
        tools = QHBoxLayout()
        tools.setSpacing(5)
        for action in ('REPEATMODE', 'SOUND'):
            cap = self._cap(action, compact=True)
            if cap:
                tools.addWidget(cap)
        panel.addLayout(tools)
        # Custom layouts can add commands without losing them in the spatial view.
        remaining = [item for item in self._items if item['code'] not in self.crs]
        if remaining:
            panel.addWidget(self._title('其他操作'))
            grid = QGridLayout()
            grid.setSpacing(5)
            for index, item in enumerate(remaining):
                grid.addWidget(self._cap(item['action'], compact=True, item=item), index // 3, index % 3)
            panel.addLayout(grid)
        panel.addStretch()
        return panel

    def setAvailableLayouts(self, layouts, active):
        # Kept for the host's shared view interface; desktop commands stay together.
        pass

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
        for cap in self.crs.values():
            cap.reset()

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
        self.setStyleSheet(
            'VirtualKeyboardView, QScrollArea, QScrollArea > QWidget > QWidget { background: %s; }'
            'QLabel#guideHint { color: %s; }'
            'QLabel#morseInput { background: %s; color: %s; border: 1px solid %s;'
            'border-radius: 7px; padding: 9px 15px; font-size: 17px; font-weight: bold; }'
            % (colors['background'], colors['muted'], colors['input'], colors['accent'], colors['border'])
        )
        for cap in self.crs.values():
            cap.updateView()
        self.update()

    def closeEvent(self, event):
        event.ignore()
        self.showMinimized()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_P and event.modifiers() & Qt.ControlModifier and event.modifiers() & Qt.ShiftModifier:
            self.settingsRequested.emit()
        else:
            super().keyPressEvent(event)

    def updateSoundSupport(self):
        return True
