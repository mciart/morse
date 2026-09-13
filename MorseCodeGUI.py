# Standard library imports
import json
import logging
import os
import sys
import time

# Third-party imports
from PyQt5 import QtCore
from PyQt5.QtMultimedia import QAudioDeviceInfo, QAudio
from PyQt5.QtCore import pyqtSignal, QTimer, Qt, QLocale, QTranslator, QLibraryInfo
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import (QAction, QCheckBox, QComboBox, QDialog, QGridLayout, QSpinBox,
                             QGroupBox, QHBoxLayout, QLabel, QMessageBox,
                             QPushButton, QRadioButton, QSystemTrayIcon, QVBoxLayout,
                             QWidget, QApplication, QMenu, QScrollArea, QKeySequenceEdit)
import keyboard
import mouse
# Local application/library specific imports
import icons_rc
from ui_theme import ThemeManager
from keyboard_output import KeyboardOutput
from virtual_keyboard import VirtualKeyboardView
from morse_engine import MorseEngine
from input_listener import KeyListenerThread
from tone_audio import ToneAudio
from windows_integration import (StartupRegistration, GlobalHotkey, parse_hotkey,
                                 DEFAULT_GLOBAL_HOTKEY, show_guide_without_activation)
from app_paths import bootstrap_assets, layouts_seed_path
from app_paths import user_data_dir as writable_user_data_dir


# Logging is installed by the executable; importing the UI never overwrites logs.

# # If you want to the console
# logging.basicConfig(level=logging.DEBUG,format='%(name)s - %(levelname)s - %(message)s')

# If configfile file is lost.. 
DEFAULT_CONFIG = {
  "theme": "system",
  "guide_auto_fit": True,
  "guide_compact": False,
  "guide_compact_scale": None,
  "guide_positions": None,
  "show_mouse": False,
  "keylen": 1,
  "keyone": "SPACE",
  "keytwo": "ENTER",
  "keythree": "RCTRL",
  "maxDitTime": 0,
  "minLetterPause": 0,
  "keyer_mode": "manual",
  "wpm": 15,
  "tone_frequency": 600,
  "tone_volume": 30,
  "confirmation_sound": False,
  "audio_device": "",
  "withsound": True,
  "off": False,
  "fontsizescale": 100,
  "upperchars": True,
  "autostart": False,
  "guide_hotkey": DEFAULT_GLOBAL_HOTKEY,
  "winxaxis": "left",
  "winyaxis": "top",
  "winposx": 10,
  "winposy": 10
}


class AudioDeviceSelector(QWidget):
    deviceChanged = pyqtSignal(str)

    def __init__(self, audio, parent=None, device_name=""):
        super().__init__(parent, Qt.Window)
        self.audio = audio
        self.setWindowTitle('音频设备')
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('选择音频设备：'))
        self.device_selector = QComboBox()
        self.device_selector.addItem('跟随系统默认设备', '')
        for device in QAudioDeviceInfo.availableDevices(QAudio.AudioOutput):
            name = device.deviceName()
            if self.device_selector.findData(name) < 0:
                self.device_selector.addItem(name, name)
        self.device_selector.setCurrentIndex(max(0, self.device_selector.findData(device_name)))
        self.device_selector.currentIndexChanged.connect(self.device_changed)
        layout.addWidget(self.device_selector)
        self.test_audio_button = QPushButton('播放测试音')
        self.test_audio_button.clicked.connect(self.test_audio)
        layout.addWidget(self.test_audio_button)
        self.status_label = QLabel('测试音使用当前音高与音量。')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.audio.error.connect(self.status_label.setText)
        self.setWindowIcon(QIcon(':/morse-writer.ico'))

    def device_changed(self, _index):
        name = self.device_selector.currentData()
        self.audio.set_device(name or None)
        self.deviceChanged.emit(name)

    def test_audio(self):
        self.status_label.setText('正在试听；测试音会自动停止。')
        self.audio.preview()


class ConfigManager:
    def __init__(self, config_file=None, default_config=DEFAULT_CONFIG):
        self.key_data = {
        "A": {'label': 'a', 'key_code': 'a', 'character': 'a', 'arg': None},
        "B": {'label': 'b', 'key_code': 'b', 'character': 'b', 'arg': None},
        "C": {'label': 'c', 'key_code': 'c', 'character': 'c', 'arg': None},
        "D": {'label': 'd', 'key_code': 'd', 'character': 'd', 'arg': None},
        "E": {'label': 'e', 'key_code': 'e', 'character': 'e', 'arg': None},
        "F": {'label': 'f', 'key_code': 'f', 'character': 'f', 'arg': None},
        "G": {'label': 'g', 'key_code': 'g', 'character': 'g', 'arg': None},
        "H": {'label': 'h', 'key_code': 'h', 'character': 'h', 'arg': None},
        "I": {'label': 'i', 'key_code': 'i', 'character': 'i', 'arg': None},
        "J": {'label': 'j', 'key_code': 'j', 'character': 'j', 'arg': None},
        "K": {'label': 'k', 'key_code': 'k', 'character': 'k', 'arg': None},
        "L": {'label': 'l', 'key_code': 'l', 'character': 'l', 'arg': None},
        "M": {'label': 'm', 'key_code': 'm', 'character': 'm', 'arg': None},
        "N": {'label': 'n', 'key_code': 'n', 'character': 'n', 'arg': None},
        "O": {'label': 'o', 'key_code': 'o', 'character': 'o', 'arg': None},
        "P": {'label': 'p', 'key_code': 'p', 'character': 'p', 'arg': None},
        "Q": {'label': 'q', 'key_code': 'q', 'character': 'q', 'arg': None},
        "R": {'label': 'r', 'key_code': 'r', 'character': 'r', 'arg': None},
        "S": {'label': 's', 'key_code': 's', 'character': 's', 'arg': None},
        "T": {'label': 't', 'key_code': 't', 'character': 't', 'arg': None},
        "U": {'label': 'u', 'key_code': 'u', 'character': 'u', 'arg': None},
        "V": {'label': 'v', 'key_code': 'v', 'character': 'v', 'arg': None},
        "W": {'label': 'w', 'key_code': 'w', 'character': 'w', 'arg': None},
        "X": {'label': 'x', 'key_code': 'x', 'character': 'x', 'arg': None},
        "Y": {'label': 'y', 'key_code': 'y', 'character': 'y', 'arg': None},
        "Z": {'label': 'z', 'key_code': 'z', 'character': 'z', 'arg': None},
        "ONE": {'label': '1', 'key_code': '1', 'character': '1', 'arg': None},
        "TWO": {'label': '2', 'key_code': '2', 'character': '2', 'arg': None},
        "THREE": {'label': '3', 'key_code': '3', 'character': '3', 'arg': None},
        "FOUR": {'label': '4', 'key_code': '4', 'character': '4', 'arg': None},
        "FIVE": {'label': '5', 'key_code': '5', 'character': '5', 'arg': None},
        "SIX": {'label': '6', 'key_code': '6', 'character': '6', 'arg': None},
        "SEVEN": {'label': '7', 'key_code': '7', 'character': '7', 'arg': None},
        "EIGHT": {'label': '8', 'key_code': '8', 'character': '8', 'arg': None},
        "NINE": {'label': '9', 'key_code': '9', 'character': '9', 'arg': None},
        "ZERO": {'label': '0', 'key_code': '0', 'character': '0', 'arg': None},
        "BACKTICK": {'label': '`', 'key_code': '`', 'character': '`', 'arg': None},
        "DOT": {'label': '.', 'key_code': '.', 'character': '.', 'arg': None},
        "COMMA": {'label': ',', 'key_code': ',', 'character': ',', 'arg': None},
        "QUESTION": {'label': '?', 'key_code': 'shift+/', 'character': '?', 'arg': None},
        "EXCLAMATION": {'label': '!', 'key_code': 'shift+1', 'character': '!', 'arg': None},
        "COLON": {'label': ':', 'key_code': 'shift+;', 'character': ':', 'arg': None},
        "SEMICOLON": {'label': ';', 'key_code': ';', 'character': ';', 'arg': None},
        "AT": {'label': '@', 'key_code': 'shift+2', 'character': '@', 'arg': None},
        "HASH": {'label': '#', 'key_code': 'shift+3', 'character': '#', 'arg': None},
        "DOLLAR": {'label': '$', 'key_code': 'shift+4', 'character': '$', 'arg': None},
        "PERCENT": {'label': '%', 'key_code': 'shift+5', 'character': '%', 'arg': None},
        "AMPERSAND": {'label': '&', 'key_code': 'shift+7', 'character': '&', 'arg': None},
        "STAR": {'label': '*', 'key_code': 'shift+8', 'character': '*', 'arg': None},
        "PLUS": {'label': '+', 'key_code': 'shift+=', 'character': '+', 'arg': None},
        "MINUS": {'label': '-', 'key_code': '-', 'character': '-', 'arg': None},
        "EQUALS": {'label': '=', 'key_code': '=', 'character': '=', 'arg': None},
        "FSLASH": {'label': '/', 'key_code': '/', 'character': '/', 'arg': None},
        "BSLASH": {'label': '\\', 'key_code': '\\', 'character': '\\', 'arg': None},
        "SINGLEQUOTE": {'label': "'", 'key_code': "'", 'character': "'", 'arg': None},
        "DOUBLEQUOTE": {'label': '"', 'key_code': "shift+'", 'character': '"', 'arg': None},
        "OPENBRACKET": {'label': '(', 'key_code': 'shift+9', 'character': '(', 'arg': None},
        "CLOSEBRACKET": {'label': ')', 'key_code': 'shift+0', 'character': ')', 'arg': None},
        "LESSTHAN": {'label': '<', 'key_code': 'shift+,', 'character': '<', 'arg': None},
        "MORETHAN": {'label': '>', 'key_code': 'shift+.', 'character': '>', 'arg': None},
        "CIRCONFLEX": {'label': '^', 'key_code': 'shift+6', 'character': '^', 'arg': None},
        "ENTER": {'label': '回车', 'key_code': 'enter', 'character': '\n', 'arg': None},
        "SPACE": {'label': '空格', 'key_code': 'space', 'character': ' ', 'arg': None},
        "BACKSPACE": {'label': '退格', 'key_code': 'backspace', 'character': '\x08', 'arg': None},
        "TAB": {'label': 'tab', 'key_code': 'tab', 'character': '\t', 'arg': None},
        "TABLEFT": {'label': '左向Tab', 'key_code': 'shift+tab', 'character': None, 'arg': None},
        "UNDERSCORE": {'label': '_', 'key_code': 'shift+-', 'character': '_', 'arg': None},
        "PAGEUP": {'label': '上一页', 'key_code': 'page_up', 'character': None, 'arg': None},
        "PAGEDOWN": {'label': '下一页', 'key_code': 'page_down', 'character': None, 'arg': None},
        "LEFTARROW": {'label': '左', 'key_code': 'left', 'character': None, 'arg': None},
        "RIGHTARROW": {'label': '右', 'key_code': 'right', 'character': None, 'arg': None},
        "UPARROW": {'label': '上', 'key_code': 'up', 'character': None, 'arg': None},
        "DOWNARROW": {'label': '下', 'key_code': 'down', 'character': None, 'arg': None},
        "ESCAPE": {'label': 'esc', 'key_code': 'esc', 'character': None, 'arg': None},
        "HOME": {'label': '行首', 'key_code': 'home', 'character': None, 'arg': None},
        "END": {'label': '行尾', 'key_code': 'end', 'character': None, 'arg': None},
        "DELETE": {'label': '删除', 'key_code': 'delete', 'character': None, 'arg': None},
        "SHIFT": {'label': 'shift', 'key_code': 'shift', 'character': None, 'arg': None, 'toggle_action': True},
        "RSHIFT": {'label': '右Shift', 'key_code': 'right shift', 'character': None, 'arg': None, 'toggle_action': True},
        "LSHIFT": {'label': '左Shift', 'key_code': 'left shift', 'character': None, 'arg': None, 'toggle_action': True},
        "CTRL": {'label': 'ctrl', 'key_code': 'ctrl', 'character': None, 'arg': None, 'toggle_action': True},
        "RCTRL": {'label': '右Ctrl', 'key_code': 'right ctrl', 'character': None, 'arg': None, 'toggle_action': True},
        "LCTRL": {'label': '左Ctrl', 'key_code': 'left ctrl', 'character': None, 'arg': None, 'toggle_action': True},
        "ALT": {'label': 'alt', 'key_code': 'alt', 'character': None, 'arg': None, 'toggle_action': True},
        "INSERT": {'label': '插入', 'key_code': 'insert', 'character': None, 'arg': None},
        "WINDOWS": {'label': 'win', 'key_code': 'windows', 'character': None, 'arg': None, 'toggle_action': True},
        "STARTMENU": {'label': '开始菜单', 'key_code': 'windows', 'character': None, 'arg': None},
        "APPLICATION": {'label': '应用菜单', 'key_code': 'menu', 'character': None, 'arg': None},
        "CAPSLOCK": {'label': '大写锁定', 'key_code': 'caps lock', 'character': None, 'arg': None},
        "F1": {'label': 'F1', 'key_code': 'f1', 'character': None, 'arg': None},
        "F2": {'label': 'F2', 'key_code': 'f2', 'character': None, 'arg': None},
        "F3": {'label': 'F3', 'key_code': 'f3', 'character': None, 'arg': None},
        "F4": {'label': 'F4', 'key_code': 'f4', 'character': None, 'arg': None},
        "F5": {'label': 'F5', 'key_code': 'f5', 'character': None, 'arg': None},
        "F6": {'label': 'F6', 'key_code': 'f6', 'character': None, 'arg': None},
        "F7": {'label': 'F7', 'key_code': 'f7', 'character': None, 'arg': None},
        "F8": {'label': 'F8', 'key_code': 'f8', 'character': None, 'arg': None},
        "F9": {'label': 'F9', 'key_code': 'f9', 'character': None, 'arg': None},
        "F10": {'label': 'F10', 'key_code': 'f10', 'character': None, 'arg': None},
        "F11": {'label': 'F11', 'key_code': 'f11', 'character': None, 'arg': None},
        "F12": {'label': 'F12', 'key_code': 'f12', 'character': None, 'arg': None},
        "REPEATMODE": {'label': '修饰键锁定', 'key_code': 'REPEATMODE', 'character': None, 'arg': 0},
        "SOUND": {'label': '提示音', 'key_code': 'unknown', 'character': None, 'arg': 8},
        "MOUSERIGHT5": {'label': '右移5', 'key_code': 'MOUSERIGHT5', 'character': None, 'arg': 2},
        "MOUSEUP5": {'label': '上移5', 'key_code': 'MOUSEUP5', 'character': None, 'arg': 3},
        "MOUSECLICKLEFT": {'label': '左键单击', 'key_code': 'MOUSECLICKLEFT', 'character': None, 'arg': 4},
        "MOUSEDBLCLICKLEFT": {'label': '左键双击', 'key_code': 'MOUSEDBLCLICKLEFT', 'character': None, 'arg': 5},
        "MOUSECLKHLDLEFT": {'label': '按住左键', 'key_code': 'MOUSECLKHLDLEFT', 'character': None, 'arg': 6},
        "MOUSEUPLEFT5": {'label': '左上5', 'key_code': 'MOUSEUPLEFT5', 'character': None, 'arg': 7},
        "MOUSEDOWNLEFT5": {'label': '左下5', 'key_code': 'MOUSEDOWNLEFT5', 'character': None, 'arg': 8},
        "MOUSERELEASEHOLD": {'label': '松开鼠标', 'key_code': 'MOUSERELEASEHOLD', 'character': None, 'arg': 9},
        "MOUSELEFT5": {'label': '左移5', 'key_code': 'MOUSELEFT5', 'character': None, 'arg': 0},
        "MOUSEDOWN5": {'label': '下移5', 'key_code': 'MOUSEDOWN5', 'character': None, 'arg': 1},
        "MOUSECLICKRIGHT": {'label': '右键单击', 'key_code': 'MOUSECLICKRIGHT', 'character': None, 'arg': 2},
        "MOUSEDBLCLICKRIGHT": {'label': '右键双击', 'key_code': 'MOUSEDBLCLICKRIGHT', 'character': None, 'arg': 3},
        "MOUSECLKHLDRIGHT": {'label': '按住右键', 'key_code': 'MOUSECLKHLDRIGHT', 'character': None, 'arg': 4},
        "MOUSEUPRIGHT5": {'label': '右上5', 'key_code': 'MOUSEUPRIGHT5', 'character': None, 'arg': 5},
        "MOUSEDOWNRIGHT5": {'label': '右下5', 'key_code': 'MOUSEDOWNRIGHT5', 'character': None, 'arg': 6},
        "MOUSENORMALMODE": {'label': '普通模式', 'key_code': 'NORMALMODE', 'character': None, 'arg': 7},
        "MOUSEUP40": {'label': '上移40', 'key_code': 'MOUSEUP40', 'character': None, 'arg': 8},
        "MOUSEUP250": {'label': '上移250', 'key_code': 'MOUSEUP250', 'character': None, 'arg': 9},
        "MOUSEDOWN40": {'label': '下移40', 'key_code': 'MOUSEDOWN40', 'character': None, 'arg': 0},
        "MOUSEDOWN250": {'label': '下移250', 'key_code': 'MOUSEDOWN250', 'character': None, 'arg': 1},
        "MOUSELEFT40": {'label': '左移40', 'key_code': 'MOUSELEFT40', 'character': None, 'arg': 2},
        "MOUSELEFT250": {'label': '左移250', 'key_code': 'MOUSELEFT250', 'character': None, 'arg': 3},
        "MOUSERIGHT40": {'label': '右移40', 'key_code': 'MOUSERIGHT40', 'character': None, 'arg': 4},
        "MOUSERIGHT250": {'label': '右移250', 'key_code': 'MOUSERIGHT250', 'character': None, 'arg': 5},
        "MOUSEUPLEFT40": {'label': '左上40', 'key_code': 'MOUSEUPLEFT40', 'character': None, 'arg': 6},
        "MOUSEUPLEFT250": {'label': '左上250', 'key_code': 'MOUSEUPLEFT250', 'character': None, 'arg': 7},
        "MOUSEDOWNLEFT40": {'label': '左下40', 'key_code': 'MOUSEDOWNLEFT40', 'character': None, 'arg': 8},
        "MOUSEDOWNLEFT250": {'label': '左下250', 'key_code': 'MOUSEDOWNLEFT250', 'character': None, 'arg': 9},
        "MOUSEUPRIGHT40": {'label': '右上40', 'key_code': 'MOUSEUPRIGHT40', 'character': None, 'arg': 0},
        "MOUSEUPRIGHT250": {'label': '右上250', 'key_code': 'MOUSEUPRIGHT250', 'character': None, 'arg': 1},
        "MOUSEDOWNRIGHT40": {'label': '右下40', 'key_code': 'MOUSEDOWNRIGHT40', 'character': None, 'arg': 2},
        "MOUSEDOWNRIGHT250": {'label': '右下250', 'key_code': 'MOUSEDOWNRIGHT250', 'character': None, 'arg': 3}
        }
        self.config_file = config_file or os.path.join(writable_user_data_dir(), 'config.json')
        self.default_config = default_config
        self.keystrokemap, self.keystrokes = self.initKeystrokeMap()
        self.config = self.read_config()
        self.actions = {}

    def initKeystrokeMap(self):
        keystrokemap = {}
        keystrokes = []
        for key, data in self.key_data.items():
            stroke = KeyStroke(key.upper(), data['label'], data['key_code'], data['character'])
            keystrokes.append(stroke)
            keystrokemap[key.upper()] = stroke
        return keystrokemap, keystrokes


    def read_config(self):
        if self.config_file and os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as file:
                    data = json.load(file)
                    for key in ('guide_layout', 'code_profile', 'SoundDit', 'SoundDah',
                                'SoundTyping', 'withdebug', 'debug'):
                        data.pop(key, None)
                    # self.update_keystrokes(data) # Note:cause issue to save configuration
                    self.convert_types(data)
                    if 'keyer_mode' not in data:
                        data['keyer_mode'] = 'iambic' if data.get('fastMorseMode', False) else 'manual'
                    return dict(self.default_config, **data)
            except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
                logging.warning(f"Error loading configuration: {e}")
        config = self.default_config.copy()
        config['fastMorseMode'] = config.get('fastMorseMode', False)  # Default to False if not set
        return config


    def update_keystrokes(self, data):
        for key in ['keyone', 'keytwo', 'keythree']:
            if key in data and data[key] in self.keystrokemap:
                data[key] = self.keystrokemap[data[key]]

    def convert_types(self, data):
        if 'maxDitTime' in data:
            data['maxDitTime'] = float(data['maxDitTime'])
        if 'minLetterPause' in data:
            data['minLetterPause'] = float(data['minLetterPause'])
        if 'fontsizescale' in data:
            data['fontsizescale'] = int(data['fontsizescale'])

    def save_config(self, config):
        try:
            with open(self.config_file, "w") as file:
                json.dump(config, file, indent=4)   # self.config
            self.config = dict(config)
        except Exception as e:
            logging.warning(f"Error saving configuration: {e}")

    def get_config(self):
        return self.config

    def initActions(self, window):
        actions = {}

        # Set up actions for each key based on `key_data`
        for key, value in self.key_data.items():
            label = value['label']
            key_code = value['key_code']
            character = value['character']
            arg = value['arg']
            toggle_action = value.get('toggle_action', False)

            if key.startswith('MOUSE'):
                actions[key.upper()] = lambda item, lbl=label, kc=key_code, a=arg: MouseAction(item, a, lbl, kc)
            else:
                # Correctly capture the loop variables using default values in lambda
                actions[key.upper()] = lambda item, win=window, lbl=label, kc=key_code, char=character, a=arg, tog=toggle_action: ActionKeyStroke(
                    {'label': lbl, 'key_code': kc, 'character': char, 'arg': a}, kc, tog, win)

        actions["REPEATMODE"] = lambda item, win=window: RepeatOnAction(item, repeat_on_callback=win.enableRepeatMode)
        actions["SOUND"] = lambda item, win=window: CallbackAction(item, '提示音', win.toggleSound)

        self.actions = actions
        return actions


class LayoutManager:
    def __init__(self, layout_file):
        self.layout_file = layout_file
        self.layouts = {}
        self.layout_warning = None
        self.main_layout_name = 'desktop'
        self.active_layout_name = 'desktop'
        self.load_layouts()

    def load_layouts(self):
        """Normalize old files into the single guide without rewriting them."""
        from morse_profiles import normalize_layouts
        try:
            with open(self.layout_file, 'r', encoding='utf-8') as stream:
                data = json.load(stream)
            defaults_path = layouts_seed_path()
            self._default_layout = json.loads(defaults_path.read_text(encoding='utf-8'))['layouts']['desktop']
            try:
                self.layouts = normalize_layouts(data['layouts'], self._default_layout)
            except ValueError as error:
                self._use_default_layout(error)
        except FileNotFoundError as error:
            raise ValueError('无法找到码表文件：' + str(error.filename)) from error
        except json.JSONDecodeError as error:
            raise ValueError('码表文件不是有效的 JSON') from error

    def _use_default_layout(self, error):
        from morse_profiles import normalize_layouts
        self.layout_warning = str(error)
        logging.warning('旧布局不可用，本次使用统一默认码表；原文件保留：%s', error)
        self.layouts = normalize_layouts({'desktop': self._default_layout})

    def set_actions(self, actions):
        """Bind runtime actions once, after normalizing the plain JSON data."""
        unsupported = [item.get('action') for item in self.get_active_layout()['items']
                       if item.get('action') not in actions]
        if unsupported:
            self._use_default_layout('未支持的动作：' + ', '.join(map(str, unsupported)))
        for item in self.get_active_layout()['items']:
            action_name = item.get('action')
            factory = actions.get(action_name)
            if factory is None:
                raise ValueError('统一码表存在未支持的动作：' + str(action_name))
            item['_action'] = factory(item)

    def get_active_layout(self):
        return self.layouts['desktop']

def moveMouse(x_delta, y_delta):
    logging.info(f"moveMouse to {x_delta} {y_delta}")
    # current_pos = mouse.get_position()
    # new_pos = (current_pos[0] + x_delta, current_pos[1] + y_delta)
    mouse.move(x_delta, y_delta, False)

def clickMouse(button='left', action='click'):
    logging.info(f"clickMouse to {button} {action}")
    btn = mouse.LEFT if button == 'left' else mouse.RIGHT
    if action == 'click':
        mouse.click(btn)
    elif action == 'press':
        mouse.press(btn)
    elif action == 'release':
        mouse.release(btn)


class Action (object):
    def __init__(self, item):
        self.item = item
    def getlabel (self):
        return self.item.get('label', "")
    def perform (self):
        pass


class CallbackAction(Action):
    def __init__(self, item, label, callback):
        super().__init__(item)
        self.label = label
        self.callback = callback

    def getlabel(self):
        return self.label

    def perform(self):
        self.callback()


class MouseAction(Action):
    MOVEMENTS = {
        'MOUSEUP5': (0, -5), 'MOUSEDOWN5': (0, 5),
        'MOUSELEFT5': (-5, 0), 'MOUSERIGHT5': (5, 0),
        'MOUSEUPLEFT5': (-5, -5), 'MOUSEUPRIGHT5': (5, -5),
        'MOUSEDOWNLEFT5': (-5, 5), 'MOUSEDOWNRIGHT5': (5, 5),
        'MOUSEUP40': (0, -40), 'MOUSEDOWN40': (0, 40),
        'MOUSELEFT40': (-40, 0), 'MOUSERIGHT40': (40, 0),
        'MOUSEUPLEFT40': (-40, -40), 'MOUSEUPRIGHT40': (40, -40),
        'MOUSEDOWNLEFT40': (-40, 40), 'MOUSEDOWNRIGHT40': (40, 40),
        'MOUSEUP250': (0, -250), 'MOUSEDOWN250': (0, 250),
        'MOUSELEFT250': (-250, 0), 'MOUSERIGHT250': (250, 0),
        'MOUSEUPLEFT250': (-250, -250), 'MOUSEUPRIGHT250': (250, -250),
        'MOUSEDOWNLEFT250': (-250, 250), 'MOUSEDOWNRIGHT250': (250, 250),
    }
    BUTTON_OPERATIONS = {
        'MOUSECLICKLEFT': (('click', mouse.LEFT),),
        'MOUSECLICKRIGHT': (('click', mouse.RIGHT),),
        'MOUSEDBLCLICKLEFT': (('double_click', mouse.LEFT),),
        'MOUSEDBLCLICKRIGHT': (('double_click', mouse.RIGHT),),
        'MOUSECLKHLDLEFT': (('press', mouse.LEFT),),
        'MOUSECLKHLDRIGHT': (('press', mouse.RIGHT),),
        'MOUSERELEASEHOLD': (('release', mouse.LEFT), ('release', mouse.RIGHT)),
    }

    def __init__(self, item, arg, label, key=None):
        super().__init__(item)
        self.arg = arg
        self.label = label
        self.key = key

    def getlabel (self):
        return self.label


    def perform(self):
        if self.key in self.MOVEMENTS:
            moveMouse(*self.MOVEMENTS[self.key])
            return
        operations = self.BUTTON_OPERATIONS.get(self.key)
        if operations is None:
            raise ValueError('未支持的鼠标动作：' + str(self.key))
        for operation, button in operations:
            if operation == 'double_click':
                mouse.double_click(button=button)
            else:
                clickMouse(button, operation)


class KeyStroke:
    def __init__(self, name, label, key_code, character):
        self.name = name
        self.label = label
        self.key_code = key_code
        self.character = character


class ActionKeyStroke(Action):
    def __init__(self, item, key, toggle_action=False, window=None):
        super(ActionKeyStroke, self).__init__(item)
        self.key = key
        self.label = item.get('label', item.get('action'))
        self.toggle_action = toggle_action
        self.window = window

    @property
    def name(self):
        return self.key

    @property
    def repeaton(self):
        return self.window.repeaton  # Access dynamically

    def set_repeaton(self, repeaton):
        self.window.repeaton = repeaton

    def getlabel(self):
        # Returns the label associated with this action, if any.
        return self.label

    def perform(self):
        self.window.key_output.send(
            self.key, self.item.get('character'), modifier=self.toggle_action)


class RepeatOnAction(Action):
    def __init__(self, item, repeat_on_callback):
        super(RepeatOnAction, self).__init__(item)
        self.repeat_on_callback = repeat_on_callback

    def getlabel(self):
        return '修饰键锁定'

    def perform(self):
        if callable(self.repeat_on_callback):
            self.repeat_on_callback()
        else:
            raise ValueError("Repeat On callback is not callable")

class Window(QDialog):
    def __init__(self, layoutManager=None, configManager=None):
        super(Window, self).__init__()
        self.layoutManager = layoutManager
        self.configManager = configManager
        self.config = self.configManager.get_config()
        self.key_output = KeyboardOutput()
        self.actions = {}
        self.keystrokes = []
        self.keystrokemap = {}
        logging.info(f"Window initialized with layout: {self.layoutManager.main_layout_name}")

        self.listenerThread = None
        self.currentCharacter = []
        self.codeslayoutview = None

        self.repeaton = False

        self._shutting_down = False
        self._start_hidden = False
        self._desktop_integration_started = False
        self.startup_registration = StartupRegistration()
        self.guide_hotkey = GlobalHotkey(self)
        self.guide_hotkey.activated.connect(self.toggleGuideVisibility)
        self.guide_hotkey.error.connect(self.hotkeyError)
        self.guide_hotkey.ready.connect(self.hotkeyReady)
        self.engine = MorseEngine(self.config)
        self.engine_timer = QTimer(self)
        self.engine_timer.setTimerType(Qt.PreciseTimer)
        self.engine_timer.setInterval(2)
        self.engine_timer.timeout.connect(self.advanceEngine)
        self.audio = ToneAudio(self)
        self.audio.error.connect(self.audioError)
        self.audioSelector = AudioDeviceSelector(self.audio, self, self.config.get('audio_device', ''))
        self.audioSelector.deviceChanged.connect(self.saveAudioDevice)
        self.configureAudio()
        app = QApplication.instance()
        app.theme_manager.set_mode(self.config.get('theme', 'system'))
        app.theme_manager.themeChanged.connect(self.refreshTheme)
        app.aboutToQuit.connect(self.shutdown)

    def load_default_config(self):
        return DEFAULT_CONFIG.copy()

    def init(self):
        if self.layoutManager.layout_warning and not self._start_hidden:
            warning = self.layoutManager.layout_warning
            self.layoutManager.layout_warning = None
            QMessageBox.warning(self, '旧布局已恢复',
                                '旧布局含重复编码或不支持的动作，本次使用统一默认码表；原文件保留。\n\n' + warning)
        self.engine_timer.stop()
        self.audio.stop()
        self.engine = MorseEngine(self.config)
        self.configureAudio()
        self.resetOutput()
        self.currentCharacter = []
        self.repeaton = False
        self.showCodeView()

    def postInit(self):
        # Initialize components that depend on actions being available
        self.actions = self.configManager.actions
        self.keystrokes = self.configManager.keystrokes
        self.keystrokemap = self.configManager.keystrokemap
        self.createIconGroupBox()
        self.createActions()
        self.createTrayIcon()
        self.trayIcon.activated.connect(self.iconActivated)
        self.GOButton.clicked.connect(self.goForIt)
        self.SaveButton.clicked.connect(self.saveSettings)
        self.DeviceButton.clicked.connect(self.changeAudioDevice)
        self.withSound.clicked.connect(self.updateAudioProperties)
        mainLayout = QVBoxLayout()
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QScrollArea.NoFrame)
        self.settings_scroll.setWidget(self.iconGroupBox)
        mainLayout.addWidget(self.settings_scroll, 1)
        self.settings_actions = QWidget()
        buttons = QHBoxLayout(self.settings_actions)
        buttons.setContentsMargins(0, 0, 0, 0)
        for button in (self.DeviceButton, self.SaveButton, self.GOButton):
            buttons.addWidget(button)
        mainLayout.addWidget(self.settings_actions)
        self.setLayout(mainLayout)
        self.setIcon()
        self.trayIcon.show()
        self.updateTrayInputState()
        self.setWindowTitle("摩斯输入设置")
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.setMinimumSize(320, 240)
        available = QApplication.desktop().availableGeometry(self)
        self.resize(min(460, available.width() - 32), min(680, available.height() - 64))


    def get_configured_keys(self):
        key_codes = []
        default_keys = {'keyone': 'SPACE', 'keytwo': 'ENTER', 'keythree': 'RCTRL'}
        key_count = int(self.config.get('keylen', 1))

        for key in ['keyone', 'keytwo', 'keythree'][:key_count]:
            config_key = self.config.get(key, default_keys[key])
            try:
                if config_key in ('MOUSE_X1', 'MOUSE_X2'):
                    key_codes.append('mouse:' + config_key[-2:].lower())
                    continue
                if config_key in {f'F{number}' for number in range(13, 25)}:
                    key_codes.append(config_key.lower())
                    continue
                # Ensure keys are fetched in uppercase, which seems to be the format used in keystrokemap
                key_code = self.keystrokemap[config_key.upper()].key_code
                key_codes.append(key_code)
            except KeyError:
                logging.error(f"Configured key '{config_key}' not found in keystroke map.")
                raise ValueError(f"Configured key '{config_key}' is invalid.")
            except AttributeError:
                logging.error(f"'KeyStroke' object for '{config_key}' is missing 'key_code' attribute.")
                raise
        return key_codes


    def startKeyListener(self):
        if self.config.get('off', False) or self._shutting_down:
            return
        key_codes = self.get_configured_keys()
        logging.debug(f"[Window startKeyListener] Configured keys: {key_codes}")
        if not self.listenerThread:
            self.audio.prepare()
            self.input_started_at = time.monotonic()
            self.listenerThread = KeyListenerThread(configured_keys=key_codes)
            self.listenerThread.timedKeyEvent.connect(self.handle_key_event)
            self.listenerThread.listenerError.connect(self.inputError)
            self.listenerThread.start()
            self.engine_timer.start()
        self.updateTrayInputState()


    def updateAudioProperties(self):
        self.config['withsound'] = self.withSound.isChecked()
        self.configureAudio()

    def configureAudio(self):
        self.audio.configure(frequency=self.config.get('tone_frequency', 600),
                             volume=self.config.get('tone_volume', 30) / 100,
                             enabled=self.config.get('withsound', True),
                             confirmation_enabled=self.config.get('confirmation_sound', False))
        self.audio.set_device(self.config.get('audio_device') or None)

    def previewAudioSettings(self, _value=None):
        self.config['tone_frequency'] = self.toneFrequencyEdit.value()
        self.config['tone_volume'] = self.toneVolumeEdit.value()
        self.config['confirmation_sound'] = self.confirmationSoundCheck.isChecked()
        self.configureAudio()

    def saveAudioDevice(self, name):
        self.config['audio_device'] = name
        self.configManager.config['audio_device'] = name
        self.configManager.save_config(self.configManager.config)

    def audioError(self, message):
        logging.error('Audio output: %s', message)
        if self.codeslayoutview is not None and hasattr(self.codeslayoutview, 'showMessage'):
            self.codeslayoutview.showMessage('音频不可用：' + message, False)

    def inputError(self, message):
        if self._shutting_down or (self.sender() is not None and self.sender() is not self.listenerThread):
            return
        logging.error('Input listener: %s', message)
        self.backToSettings()
        QMessageBox.warning(self, '输入设备不可用', message)


    def showCodeView(self):
        view = VirtualKeyboardView(self.layoutManager.get_active_layout(), self.config)
        # Keep a strong Python reference, but no native owner: an owned window
        # disappears from the Windows taskbar when the settings window hides.
        # stopIt() explicitly hides and deletes the guide.
        view.setWindowIcon(self.windowIcon())
        self.codeslayoutview = view
        view.settingsRequested.connect(self.backToSettings)
        view.mouseVisibilityChanged.connect(self.changeMouseVisibility)
        view.autoFitChanged.connect(self.changeGuideAutoFit)
        view.compactModeChanged.connect(self.changeGuideCompact)
        view.compactScaleChanged.connect(self.changeGuideCompactScale)
        view.guidePositionsChanged.connect(self.changeGuidePositions)
        self.updateOutputState()
        if not self._start_hidden:
            view.show()

    def refreshTheme(self, _resolved=None):
        if self.codeslayoutview is not None:
            if hasattr(self.codeslayoutview, 'updateTheme'):
                self.codeslayoutview.updateTheme()
            self.updateOutputState()

    def changeTheme(self):
        mode = self.themeComboBox.currentData()
        self.config['theme'] = mode
        self.configManager.config['theme'] = mode
        QApplication.instance().theme_manager.set_mode(mode)
        self.configManager.save_config(self.configManager.config)

    def changeMouseVisibility(self, visible):
        self.config['show_mouse'] = bool(visible)
        self.configManager.config['show_mouse'] = bool(visible)
        self.showMouseCheckBox.setChecked(bool(visible))
        if isinstance(self.codeslayoutview, VirtualKeyboardView):
            self.codeslayoutview.setMouseVisible(bool(visible))
        self.configManager.save_config(self.configManager.config)

    def changeGuideAutoFit(self, enabled):
        self.config['guide_auto_fit'] = bool(enabled)
        self.configManager.config['guide_auto_fit'] = bool(enabled)
        self.guideAutoFitCheckBox.setChecked(bool(enabled))
        if isinstance(self.codeslayoutview, VirtualKeyboardView):
            self.codeslayoutview.setAutoFit(bool(enabled))
        self.configManager.save_config(self.configManager.config)

    def updateOutputState(self):
        if self.codeslayoutview is not None:
            self.codeslayoutview.setOutputState(self.key_output.held_modifiers, self.repeaton)

    def changeGuideCompact(self, enabled):
        enabled = bool(enabled)
        self.config['guide_compact'] = enabled
        self.configManager.config['guide_compact'] = enabled
        self.guideCompactCheckBox.setChecked(enabled)
        self.compactGuideAction.setChecked(enabled)
        if isinstance(self.codeslayoutview, VirtualKeyboardView):
            self.codeslayoutview.setCompactMode(enabled)
        self.configManager.save_config(self.configManager.config)

    def changeGuideCompactScale(self, scale):
        self.config['guide_compact_scale'] = float(scale)
        self.configManager.config['guide_compact_scale'] = float(scale)
        self.configManager.save_config(self.configManager.config)

    def changeGuidePositions(self, positions):
        self.config['guide_positions'] = dict(positions)
        self.configManager.config['guide_positions'] = dict(positions)
        self.configManager.save_config(self.configManager.config)

    def toggleSound(self):
        self.config['withsound'] = not self.config['withsound']
        self.withSound.setChecked(self.config['withsound'])
        self.updateAudioProperties()
        self.updateOutputState()


    def collect_config(self):
        config = {
            **self.config,
            'theme': self.themeComboBox.currentData(),
            'show_mouse': self.showMouseCheckBox.isChecked(),
            'guide_auto_fit': self.guideAutoFitCheckBox.isChecked(),
            'guide_compact': self.guideCompactCheckBox.isChecked(),
            'keylen': self.keySelectionRadioOneKey.isChecked() and 1 or self.keySelectionRadioTwoKey.isChecked() and 2 or 3,
            'keyone': self.iconComboBoxKeyOne.itemData(self.iconComboBoxKeyOne.currentIndex()),
            'keytwo': self.iconComboBoxKeyTwo.itemData(self.iconComboBoxKeyTwo.currentIndex()),
            'keythree': self.iconComboBoxKeyThree.itemData(self.iconComboBoxKeyThree.currentIndex()),
            'maxDitTime': self.maxDitTimeEdit.value() if self.customTimingCheck.isChecked() else 0,
            'minLetterPause': self.minLetterPauseEdit.value() if self.customTimingCheck.isChecked() else 0,
            'keyer_mode': 'iambic' if self.fastMorseModeCheckbox.isChecked() else 'manual',
            'wpm': self.wpmEdit.value(),
            'tone_frequency': self.toneFrequencyEdit.value(),
            'tone_volume': self.toneVolumeEdit.value(),
            'confirmation_sound': self.confirmationSoundCheck.isChecked(),
            'withsound': self.withSound.isChecked(),
            'off': False,
            'fontsizescale': self.fontSizeScaleEdit.value(),
            'autostart': self.autostartCheckbox.isChecked(),
            'guide_hotkey': self.selectedGuideHotkey(),
            'fastMorseMode': self.fastMorseModeCheckbox.isChecked() if self.keySelectionRadioOneKey.isChecked() is False else False,
        }
        return config

    def goForIt(self):
        key_one = self.iconComboBoxKeyOne.currentData()
        key_two = self.iconComboBoxKeyTwo.currentData()
        key_three = self.iconComboBoxKeyThree.currentData()
        warn_user = (self.keySelectionRadioTwoKey.isChecked() and key_one == key_two) or (self.keySelectionRadioThreeKey.isChecked() and (key_one == key_two or key_one == key_three or key_two == key_three))

        if warn_user:
            QMessageBox.warning(self, "摩斯输入",
                                    "输入按键不能重复，请为每个位置选择不同的按键。")
            return

        try:
            self.config = self.collect_config()
        except (ValueError, TypeError):
            QMessageBox.warning(self, '设置无效', '请检查输入及声音设置。')
            return
        self.hide()
        self.init()
        if not self.listenerThread:
            self.startKeyListener()
        self.applyGuideHotkey()

    def start (self):
        self.init()
        self.startKeyListener()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def quitApplication(self):
        self.shutdown()
        self.audioSelector.hide()
        self.hide()
        self.trayIcon.hide()
        QApplication.instance().quit()

    def shutdown(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        for cleanup in (self.guide_hotkey.stop, self.stopIt, self.resetOutput, self.audio.shutdown):
            try:
                cleanup()
            except Exception:
                logging.exception('Application cleanup failed: %s', cleanup.__name__)
        logging.info('Input hooks, output state and audio stopped')

    def resetOutput(self):
        try:
            self.key_output.reset()
            return True
        except Exception:
            # A device/output failure must never prevent timers/audio/Qt
            # objects from being stopped. Failed modifiers remain retryable.
            logging.exception('Unable to release one or more output modifiers')
            return False

    def setIcon(self):
        icon = QIcon(':/morse-writer.ico')
        self.trayIcon.setIcon(icon)
        self.setWindowIcon(icon)

    def iconActivated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.showCurrentWindow()

    def showCurrentWindow(self):
        target = self.codeslayoutview if self.codeslayoutview is not None else self
        if target is self:
            target.showNormal()
            target.raise_()
            target.activateWindow()
        else:
            show_guide_without_activation(target)

    def toggleGuideVisibility(self):
        target = self.codeslayoutview if self.codeslayoutview is not None else self
        if target.isVisible() and not target.isMinimized():
            target.hide()
        else:
            self.showCurrentWindow()

    def startDesktopIntegration(self):
        self._desktop_integration_started = True
        self.applyGuideHotkey()

    def selectedGuideHotkey(self):
        if not self.hotkeyEnabledCheck.isChecked():
            return ''
        sequence = self.hotkeyEdit.keySequence().toString(QKeySequence.PortableText)
        count = (1 if self.keySelectionRadioOneKey.isChecked() else
                 2 if self.keySelectionRadioTwoKey.isChecked() else 3)
        inputs = [box.currentData() for box in (
            self.iconComboBoxKeyOne, self.iconComboBoxKeyTwo,
            self.iconComboBoxKeyThree)[:count]]
        if self.listenerThread is not None:
            inputs += [self.config.get(name) for name in
                       ('keyone', 'keytwo', 'keythree')[:int(self.config.get('keylen', 1))]]
        return self.validateGuideHotkey(sequence, inputs)

    def validateGuideHotkey(self, sequence, inputs):
        canonical, _modifiers, trigger_key = parse_hotkey(sequence)
        for name in inputs:
            stroke = self.keystrokemap.get(name)
            key_name = stroke.key_code if stroke is not None else name
            try:
                # The input hook consumes its key with modifiers held too.
                _text, _mask, input_key = parse_hotkey('Ctrl+' + str(key_name))
            except ValueError:
                continue  # Mouse buttons and side-specific modifier inputs.
            if trigger_key == input_key:
                raise ValueError('码表快捷键不能与摩斯输入键相同，请选择另一个按键。')
        return canonical

    def changeGuideHotkeyPreset(self):
        sequence = self.hotkeyPresetComboBox.currentData()
        if sequence is not None:
            previous = self.hotkeyEdit.blockSignals(True)
            self.hotkeyEdit.setKeySequence(QKeySequence(sequence))
            self.hotkeyEdit.blockSignals(previous)
        self.updateGuideHotkeyControls()

    def syncGuideHotkeyPreset(self):
        sequence = self.hotkeyEdit.keySequence().toString(QKeySequence.PortableText)
        index = self.hotkeyPresetComboBox.findData(sequence)
        previous = self.hotkeyPresetComboBox.blockSignals(True)
        self.hotkeyPresetComboBox.setCurrentIndex(
            index if index >= 0 else self.hotkeyPresetComboBox.findData(None))
        self.hotkeyPresetComboBox.blockSignals(previous)
        self.updateGuideHotkeyControls()

    def updateGuideHotkeyControls(self):
        enabled = self.hotkeyEnabledCheck.isChecked() and self.guide_hotkey.supported
        self.hotkeyPresetComboBox.setEnabled(enabled)
        self.hotkeyEdit.setEnabled(enabled)
        self.hotkeyEdit.setVisible(self.hotkeyPresetComboBox.currentData() is None)

    def applyGuideHotkey(self):
        if self._desktop_integration_started:
            sequence = self.config.get('guide_hotkey', DEFAULT_GLOBAL_HOTKEY)
            if sequence:
                inputs = [self.config.get(name) for name in
                          ('keyone', 'keytwo', 'keythree')[:int(self.config.get('keylen', 1))]]
                try:
                    self.validateGuideHotkey(sequence, inputs)
                except ValueError as error:
                    self.hotkeyError(str(error))
                    return
            self.guide_hotkey.set_sequence(sequence)

    def saveGuideHotkey(self):
        try:
            sequence = self.selectedGuideHotkey()
        except ValueError as error:
            self.hotkeyError(str(error))
            return
        self.config['guide_hotkey'] = sequence
        self.configManager.config['guide_hotkey'] = sequence
        self.configManager.save_config(self.configManager.config)
        self.applyGuideHotkey()
        if not sequence:
            self.hotkeyStatus.setText('快捷键已关闭')

    def hotkeyError(self, message):
        logging.warning('Guide hotkey: %s', message)
        if hasattr(self, 'hotkeyStatus'):
            self.hotkeyStatus.setText(message)

    def hotkeyReady(self, sequence):
        self.hotkeyStatus.setText('已启用：' + sequence if sequence else '快捷键已关闭')

    def changeStartupRegistration(self, enabled):
        try:
            self.startup_registration.set_enabled(bool(enabled))
        except (OSError, RuntimeError, ValueError) as error:
            self.startupCheckbox.setChecked(not enabled)
            QMessageBox.warning(self, '开机自启设置失败', str(error))

    def presentAtLaunch(self, startup=False):
        self._start_hidden = bool(startup)
        try:
            if self.config.get('autostart', False):
                self.start()
            elif not startup:
                self.show()
        finally:
            self._start_hidden = False

    def updateTrayInputState(self):
        if hasattr(self, 'onOffAction'):
            active = self.listenerThread is not None and not self.config.get('off', False)
            self.onOffAction.setChecked(active)
            if hasattr(self, 'trayIcon'):
                self.trayIcon.setToolTip('摩斯输入 · ' + ('输入已开启' if active else '输入已暂停'))

    def mkKeyStrokeComboBox (self, items, currentkey, valuedict=None):
        box = QComboBox()
        for key, val in items:
            eval = valuedict[val] if valuedict is not None else val
            box.addItem(key, eval)
        try:
            values = list(map(lambda a:valuedict[a[1]] if valuedict is not None else a[1], items))
            box.setCurrentIndex(values.index(currentkey))
        except ValueError:
            pass
        return box

    def createIconGroupBox(self):
        self.iconGroupBox = QGroupBox("输入设置")

        self.keySelectionRadioOneKey = QRadioButton("单键")
        self.keySelectionRadioTwoKey = QRadioButton("双键")
        self.keySelectionRadioThreeKey = QRadioButton("三键")

        inputSettingsLayout = QVBoxLayout()

        inputRadioGroup = QGroupBox("按键数量")
        inputRadioButtonsLayout = QHBoxLayout()
        inputRadioButtonsLayout.addWidget(self.keySelectionRadioOneKey)
        inputRadioButtonsLayout.addWidget(self.keySelectionRadioTwoKey)
        inputRadioButtonsLayout.addWidget(self.keySelectionRadioThreeKey)
        inputRadioGroup.setLayout(inputRadioButtonsLayout)
        inputSettingsLayout.addWidget(inputRadioGroup)

        inputKeyComboBoxesLayout = QHBoxLayout()

        # Filter the keystrokes to only include those keys that are specified in morse_keys
        morse_keys = ["SPACE", "ENTER", "ONE", "TWO", "Z", "F8", "F9", "RCTRL", "LCTRL", "RSHIFT", "LSHIFT", "ALT", "CTRL"]
        filtered_keystrokes = [(self.keystrokemap[key].label, self.keystrokemap[key].name) for key in morse_keys if key in self.keystrokemap]
        filtered_keystrokes += [(f'F{number}', f'F{number}') for number in range(13, 25)]
        filtered_keystrokes += [('鼠标 X1（侧键）', 'MOUSE_X1'), ('鼠标 X2（侧键）', 'MOUSE_X2')]

        # Set up the combo box for the first key using the filtered list
        self.iconComboBoxKeyOne = self.mkKeyStrokeComboBox(
            filtered_keystrokes,
            self.config.get('keyone')
        )

        # Repeat similar setup for other key selectors if necessary
        self.iconComboBoxKeyTwo = self.mkKeyStrokeComboBox(
            filtered_keystrokes,
            self.config.get('keytwo')
        )

        self.iconComboBoxKeyThree = self.mkKeyStrokeComboBox(
            filtered_keystrokes,
            self.config.get('keythree')
        )

        inputKeyComboBoxesLayout.addWidget(self.iconComboBoxKeyOne)
        inputKeyComboBoxesLayout.addWidget(self.iconComboBoxKeyTwo)
        inputKeyComboBoxesLayout.addWidget(self.iconComboBoxKeyThree)
        inputSettingsLayout.addLayout(inputKeyComboBoxesLayout)
        mapping_hint = QLabel('手柄映射推荐 F23 / F24；X1 / X2 也可用作输入键。')
        mapping_hint.setWordWrap(True)
        inputSettingsLayout.addWidget(mapping_hint)

        # Connect the radio buttons to updateFastMorseModeAvailability
        self.keySelectionRadioOneKey.toggled.connect(self.iconComboBoxKeyTwo.hide)
        self.keySelectionRadioOneKey.toggled.connect(self.iconComboBoxKeyThree.hide)
        self.keySelectionRadioTwoKey.toggled.connect(self.iconComboBoxKeyTwo.show)
        self.keySelectionRadioTwoKey.toggled.connect(self.iconComboBoxKeyThree.hide)
        self.keySelectionRadioThreeKey.toggled.connect(self.iconComboBoxKeyThree.show)
        self.keySelectionRadioThreeKey.toggled.connect(self.iconComboBoxKeyTwo.show)

        self.keySelectionRadioOneKey.clicked.connect(self.updateFastMorseModeAvailability)
        self.keySelectionRadioTwoKey.clicked.connect(self.updateFastMorseModeAvailability)
        self.keySelectionRadioThreeKey.clicked.connect(self.updateFastMorseModeAvailability)

        for index, name in [[1,'One'], [2,'Two'], [3,'Three']]:
            getattr(self, 'keySelectionRadio%sKey'%(name)).setChecked(self.config.get('keylen', 1) == index)

        self.fastMorseModeCheckbox = QCheckBox('自动电键：长按连发、双键交替')
        self.fastMorseModeCheckbox.setChecked(self.config.get('keyer_mode', 'manual') == 'iambic')
        inputSettingsLayout.addWidget(self.fastMorseModeCheckbox)
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel('点划速度：'))
        self.wpmEdit = QSpinBox()
        self.wpmEdit.setRange(5, 60)
        self.wpmEdit.setValue(int(self.config.get('wpm', 15)))
        self.wpmEdit.setSuffix(' WPM')
        speed_layout.addWidget(self.wpmEdit, 1)
        self.standardKeyerButton = QPushButton('标准电键预设')
        self.standardKeyerButton.setToolTip('双键自动电键，15 WPM、600 Hz、音量 30%，使用标准点划及确认间隔。输入键保持原选择。')
        self.standardKeyerButton.clicked.connect(self.applyStandardKeyerPreset)
        speed_layout.addWidget(self.standardKeyerButton)
        inputSettingsLayout.addLayout(speed_layout)
        self.timingSummary = QLabel()
        self.timingSummary.setWordWrap(True)
        inputSettingsLayout.addWidget(self.timingSummary)
        self.wpmEdit.valueChanged.connect(self.updateTimingSummary)
        self.customTimingCheck = QCheckBox('高级：自定义识别时长')
        self.customTimingCheck.setToolTip('通常关闭即可随速度使用标准节奏；勾选后可延长单键分界或字符确认时间。')
        self.customTimingCheck.setChecked(any(float(self.config.get(name, 0)) > 0
                                             for name in ('maxDitTime', 'minLetterPause')))
        inputSettingsLayout.addWidget(self.customTimingCheck)
        self.customTimingPanel = QWidget()
        timing_layout = QGridLayout(self.customTimingPanel)
        timing_layout.setContentsMargins(0, 0, 0, 0)
        self.maxDitTimeLabel = QLabel('单键点划分界：')
        self.maxDitTimeEdit = QSpinBox()
        self.maxDitTimeEdit.setRange(0, 5000)
        self.maxDitTimeEdit.setSpecialValueText('自动（2 个点时长）')
        self.maxDitTimeEdit.setSuffix(' 毫秒')
        self.maxDitTimeEdit.setValue(round(float(self.config.get('maxDitTime', 0))))
        self.minLetterPauseLabel = QLabel('字符确认间隔：')
        self.minLetterPauseEdit = QSpinBox()
        self.minLetterPauseEdit.setRange(0, 60000)
        self.minLetterPauseEdit.setSpecialValueText('标准（3 个点时长）')
        self.minLetterPauseEdit.setSuffix(' 毫秒')
        self.minLetterPauseEdit.setValue(round(float(self.config.get('minLetterPause', 0))))
        self.minLetterPauseEdit.valueChanged.connect(self.updateTimingSummary)
        self.minLetterPauseEdit.setToolTip('设为 0 使用标准间隔；较大的数值增加输入容错。三键模式由第三键确认。')
        timing_layout.addWidget(self.maxDitTimeLabel, 0, 0)
        timing_layout.addWidget(self.maxDitTimeEdit, 0, 1)
        timing_layout.addWidget(self.minLetterPauseLabel, 1, 0)
        timing_layout.addWidget(self.minLetterPauseEdit, 1, 1)
        inputSettingsLayout.addWidget(self.customTimingPanel)
        self.customTimingCheck.toggled.connect(self.updateFastMorseModeAvailability)

        sound_group = QGroupBox('声音')
        sound_layout = QGridLayout(sound_group)
        self.withSound = QCheckBox('播放摩斯音')
        self.withSound.setChecked(self.config.get('withsound', True))
        sound_layout.addWidget(self.withSound, 0, 0)
        self.previewToneButton = QPushButton('试听')
        self.previewToneButton.clicked.connect(self.previewMorseTone)
        sound_layout.addWidget(self.previewToneButton, 0, 1)
        self.toneFrequencyEdit = QSpinBox()
        self.toneFrequencyEdit.setRange(200, 1200)
        self.toneFrequencyEdit.setSuffix(' Hz')
        self.toneFrequencyEdit.setValue(int(self.config.get('tone_frequency', 600)))
        self.toneVolumeEdit = QSpinBox()
        self.toneVolumeEdit.setRange(0, 100)
        self.toneVolumeEdit.setSuffix(' %')
        self.toneVolumeEdit.setValue(int(self.config.get('tone_volume', 30)))
        self.confirmationSoundCheck = QCheckBox('字符完成与无效码提示音')
        self.confirmationSoundCheck.setChecked(self.config.get('confirmation_sound', False))
        sound_layout.addWidget(QLabel('音高：'), 1, 0)
        sound_layout.addWidget(self.toneFrequencyEdit, 1, 1)
        sound_layout.addWidget(QLabel('音量：'), 2, 0)
        sound_layout.addWidget(self.toneVolumeEdit, 2, 1)
        sound_layout.addWidget(self.confirmationSoundCheck, 3, 0, 1, 2)
        inputSettingsLayout.addWidget(sound_group)
        for control in (self.toneFrequencyEdit, self.toneVolumeEdit):
            control.valueChanged.connect(self.previewAudioSettings)
        self.confirmationSoundCheck.toggled.connect(self.previewAudioSettings)

        appearance_group = QGroupBox('外观')
        appearance = QGridLayout(appearance_group)
        appearance.addWidget(QLabel('界面主题：'), 0, 0)
        self.themeComboBox = QComboBox()
        for label, mode in (('跟随系统', 'system'), ('浅色', 'light'), ('深色', 'dark')):
            self.themeComboBox.addItem(label, mode)
        self.themeComboBox.setCurrentIndex(max(0, self.themeComboBox.findData(self.config.get('theme', 'system'))))
        self.themeComboBox.currentIndexChanged.connect(self.changeTheme)
        appearance.addWidget(self.themeComboBox, 0, 1)
        self.guideAutoFitCheckBox = QCheckBox('码表自动适应窗口')
        self.guideAutoFitCheckBox.setChecked(self.config.get('guide_auto_fit', True))
        self.guideAutoFitCheckBox.clicked.connect(self.changeGuideAutoFit)
        appearance.addWidget(self.guideAutoFitCheckBox, 1, 0)
        self.showMouseCheckBox = QCheckBox('显示鼠标对照')
        self.showMouseCheckBox.setChecked(self.config.get('show_mouse', False))
        self.showMouseCheckBox.clicked.connect(self.changeMouseVisibility)
        appearance.addWidget(self.showMouseCheckBox, 1, 1)
        self.fontSizeScaleLabel = QLabel('码表缩放：')
        self.fontSizeScaleEdit = QSpinBox()
        self.fontSizeScaleEdit.setRange(10, max(300, round(float(self.config.get('fontsizescale', 100)))))
        self.fontSizeScaleEdit.setSuffix(' %')
        self.fontSizeScaleEdit.setValue(round(float(self.config.get('fontsizescale', 100))))
        appearance.addWidget(self.fontSizeScaleLabel, 2, 0)
        appearance.addWidget(self.fontSizeScaleEdit, 2, 1)
        self.guideCompactCheckBox = QCheckBox('精简显示：仅保留透明键位叠加层')
        self.guideCompactCheckBox.setChecked(self.config.get('guide_compact', False))
        self.guideCompactCheckBox.clicked.connect(self.changeGuideCompact)
        appearance.addWidget(self.guideCompactCheckBox, 3, 0, 1, 2)
        self.guideAutoFitCheckBox.toggled.connect(self.updateGuideScaleAvailability)
        self.updateGuideScaleAvailability()
        inputSettingsLayout.addWidget(appearance_group)

        startup_group = QGroupBox('启动与快捷键')
        startup_layout = QVBoxLayout(startup_group)
        self.startupCheckbox = QCheckBox('开机自启，并收进系统托盘')
        self.startupCheckbox.setEnabled(self.startup_registration.supported)
        try:
            self.startupCheckbox.setChecked(self.startup_registration.is_enabled())
        except (OSError, RuntimeError) as error:
            logging.warning('Startup registration: %s', error)
            self.startupCheckbox.setEnabled(False)
            self.startupCheckbox.setToolTip(str(error))
        self.startupCheckbox.clicked.connect(self.changeStartupRegistration)
        startup_layout.addWidget(self.startupCheckbox)
        self.autostartCheckbox = QCheckBox('启动后自动开始输入')
        self.autostartCheckbox.setChecked(self.config.get('autostart', False))
        startup_layout.addWidget(self.autostartCheckbox)
        self.hotkeyEnabledCheck = QCheckBox('码表显示／隐藏快捷键')
        self.hotkeyEnabledCheck.setChecked(bool(self.config.get('guide_hotkey', DEFAULT_GLOBAL_HOTKEY)))
        self.hotkeyEnabledCheck.setEnabled(self.guide_hotkey.supported)
        startup_layout.addWidget(self.hotkeyEnabledCheck)
        shortcut_row = QHBoxLayout()
        self.hotkeyEdit = QKeySequenceEdit(QKeySequence(self.config.get('guide_hotkey') or DEFAULT_GLOBAL_HOTKEY))
        self.hotkeyEdit.setToolTip('按下新的组合键后点击“应用”；未开始输入时切换设置窗口。')
        self.hotkeyPresetComboBox = QComboBox()
        self.hotkeyPresetComboBox.addItem(DEFAULT_GLOBAL_HOTKEY + '（默认）', DEFAULT_GLOBAL_HOTKEY)
        for number in range(13, 25):
            self.hotkeyPresetComboBox.addItem(f'F{number}', f'F{number}')
        self.hotkeyPresetComboBox.addItem('自定义组合键…', None)
        self.syncGuideHotkeyPreset()
        self.hotkeyPresetComboBox.currentIndexChanged.connect(self.changeGuideHotkeyPreset)
        self.hotkeyEdit.keySequenceChanged.connect(self.syncGuideHotkeyPreset)
        self.hotkeyEnabledCheck.toggled.connect(self.updateGuideHotkeyControls)
        shortcut_row.addWidget(self.hotkeyPresetComboBox, 1)
        self.hotkeyApplyButton = QPushButton('应用')
        self.hotkeyApplyButton.setEnabled(self.guide_hotkey.supported)
        self.hotkeyApplyButton.clicked.connect(self.saveGuideHotkey)
        shortcut_row.addWidget(self.hotkeyApplyButton)
        startup_layout.addLayout(shortcut_row)
        startup_layout.addWidget(self.hotkeyEdit)
        self.hotkeyStatus = QLabel('可直接选择 F22，再点击“应用”；隐藏码表时输入继续运行。')
        self.hotkeyStatus.setWordWrap(True)
        startup_layout.addWidget(self.hotkeyStatus)
        inputSettingsLayout.addWidget(startup_group)
        self.updateFastMorseModeAvailability()
        self.updateTimingSummary()

        self.DeviceButton = QPushButton("音频设备")
        self.SaveButton = QPushButton("保存设置")
        self.GOButton = QPushButton("开始输入")

        self.iconGroupBox.setLayout(inputSettingsLayout)

    def updateFastMorseModeAvailability(self):
        single = self.keySelectionRadioOneKey.isChecked()
        three = self.keySelectionRadioThreeKey.isChecked()
        self.fastMorseModeCheckbox.setEnabled(not single)
        if single:
            self.fastMorseModeCheckbox.setChecked(False)
        self.customTimingCheck.setVisible(not three)
        self.customTimingPanel.setVisible(self.customTimingCheck.isChecked() and not three)
        for control in (self.maxDitTimeLabel, self.maxDitTimeEdit):
            control.setVisible(single)
        self.updateTimingSummary()

    def updateTimingSummary(self):
        unit = 1200 / self.wpmEdit.value()
        custom = self.customTimingCheck.isChecked()
        gap = max(3 * unit, self.minLetterPauseEdit.value()) if custom else 3 * unit
        ending = '第三键确认' if self.keySelectionRadioThreeKey.isChecked() else f'确认 {gap:g} 毫秒'
        self.timingSummary.setText(f'点 {unit:g} 毫秒 · 划 {3 * unit:g} 毫秒 · {ending}')

    def updateGuideScaleAvailability(self):
        manual = not self.guideAutoFitCheckBox.isChecked()
        self.fontSizeScaleLabel.setVisible(manual)
        self.fontSizeScaleEdit.setVisible(manual)

    def applyStandardKeyerPreset(self):
        self.keySelectionRadioTwoKey.setChecked(True)
        self.fastMorseModeCheckbox.setChecked(True)
        self.wpmEdit.setValue(15)
        self.customTimingCheck.setChecked(False)
        self.maxDitTimeEdit.setValue(0)
        self.minLetterPauseEdit.setValue(0)
        self.toneFrequencyEdit.setValue(600)
        self.toneVolumeEdit.setValue(30)
        self.confirmationSoundCheck.setChecked(False)
        self.withSound.setChecked(True)
        self.updateAudioProperties()
        self.updateFastMorseModeAvailability()

    def previewMorseTone(self):
        self.previewAudioSettings()
        self.audio.preview()

    def saveSettings (self):
        try:
            self.config = self.collect_config()
        except (ValueError, TypeError):
            QMessageBox.warning(self, '设置无效', '请检查输入及声音设置。')
            return
        self.configManager.save_config(self.config)
        self.applyGuideHotkey()

    def changeAudioDevice(self):
        self.audioSelector.show()

    def toggleOnOff(self):
        if self.codeslayoutview is None:
            self.goForIt()
            self.updateTrayInputState()
            return
        self.config['off'] = not self.config.get('off', False)
        if self.config['off']:
            self.stopKeyListener()
        else:
            self.startKeyListener()
        self.updateOutputState()
        self.updateTrayInputState()

    def stopKeyListener(self):
        if self.listenerThread is not None:
            listener = self.listenerThread
            self.listenerThread = None
            listener.stop()
            try:
                listener.timedKeyEvent.disconnect(self.handle_key_event)
                listener.listenerError.disconnect(self.inputError)
            except (TypeError, RuntimeError):
                pass
            listener.deleteLater()
        self.engine_timer.stop()
        self.engine.reset()
        self.audio.stop()
        self.currentCharacter = []
        self.repeaton = False
        self.resetOutput()
        if self.codeslayoutview is not None:
            self.codeslayoutview.reset()
            self.updateOutputState()
        self.updateTrayInputState()

    def stopIt(self):
        logging.debug("Stopping components...")
        self.stopKeyListener()
        if self.codeslayoutview is not None:
            if isinstance(self.codeslayoutview, VirtualKeyboardView):
                self.codeslayoutview.flushPosition()
            self.codeslayoutview.hide()
            self.codeslayoutview.deleteLater()
            self.codeslayoutview = None
        logging.debug("All components stopped.")

    def backToSettings (self):
        self.showNormal()
        self.stopIt()

    def onOpenSettings (self):
        self.backToSettings()

    def createActions(self):
        self.showWindowAction = QAction("显示窗口", self, triggered=self.showCurrentWindow)
        self.compactGuideAction = QAction('精简显示', self, checkable=True,
                                         triggered=self.changeGuideCompact)
        self.compactGuideAction.setChecked(self.config.get('guide_compact', False))
        self.onOffAction = QAction('启用输入', self, checkable=True, triggered=self.toggleOnOff)
        self.onOpenSettingsAction = QAction("打开设置", self, triggered=self.onOpenSettings)
        self.quitAction = QAction("退出", self, triggered=self.quitApplication)

    def createTrayIcon(self):
        self.trayIconMenu = QMenu(self)
        self.trayIconMenu.addAction(self.showWindowAction)
        self.trayIconMenu.addAction(self.compactGuideAction)
        self.trayIconMenu.addAction(self.onOffAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.onOpenSettingsAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.quitAction)
        self.trayIcon = QSystemTrayIcon(self)
        self.trayIcon.setToolTip("摩斯输入")
        self.trayIcon.setContextMenu(self.trayIconMenu)

    def handle_key_event(self, key, is_press, role, timestamp=None):
        if self.listenerThread is None or self.config.get('off', False) or self._shutting_down:
            return
        sender = getattr(self, 'sender', lambda: None)()
        if sender is not None and isinstance(sender, KeyListenerThread):
            if sender is self.listenerThread:
                self.drainInput()
            return  # Signals wake the consumer; snapshots own the event data.
        # A hook timestamps input before it waits in the Qt event queue.
        now = time.monotonic() if timestamp is None else timestamp
        if now < getattr(self, 'input_started_at', 0):
            return
        self.processEngineEvents(self.engine.key(role, is_press, now))

    def advanceEngine(self):
        if self.listenerThread is not None and not self.config.get('off', False):
            self.drainInput()

    def drainInput(self):
        listener = self.listenerThread
        if listener is None:
            return
        cutoff, events = listener.snapshot_events()
        for key, is_press, role, timestamp in events:
            if listener is not self.listenerThread or self.config.get('off', False):
                return
            if timestamp >= self.input_started_at:
                self.processEngineEvents(self.engine.key(role, is_press, timestamp))
        if listener is self.listenerThread:
            self.processEngineEvents(self.engine.tick(cutoff))

    def processEngineEvents(self, events):
        for kind, payload in events:
            if kind == 'tone':
                self.audio.set_tone(payload['on'], timestamp=payload.get('at'))
            elif kind == 'symbol':
                self.addDit() if payload['symbol'] == 1 else self.addDah()
            elif kind == 'commit':
                view = self.codeslayoutview
                self.endCharacter()
                # A new key can commit the old character and begin the next in
                # one batch. Only discard it if the action switched surfaces.
                if self.codeslayoutview is not view:
                    return
            elif kind == 'feedback':
                view = self.codeslayoutview
                if view is not None and hasattr(view, 'setInputFeedback'):
                    names = {0: 'straight' if payload.get('mode') == 'straight' else 'dot',
                             1: 'dash', 2: 'commit'}
                    held = tuple(names[role] for role in payload['held'])
                    view.setInputFeedback(held, payload['progress'], payload.get('sounding'))
            elif kind == 'reset':
                self.audio.stop()
                self.currentCharacter = []
                if self.codeslayoutview is not None:
                    self.codeslayoutview.reset()
                    if payload.get('reason') in ('timing_overrun', 'late_input') and hasattr(self.codeslayoutview, 'showMessage'):
                        self.codeslayoutview.showMessage('输入已重置，请松开按键后继续', False)

    def on_press(self, key, role):
        self.handle_key_event(key, True, role)

    def on_release(self, key, role):
        self.handle_key_event(key, False, role)

    def addDit(self):
        self.currentCharacter.append(1)
        if self.codeslayoutview is not None:
            self.codeslayoutview.Dit()

    def addDah(self):
        self.currentCharacter.append(2)
        if self.codeslayoutview is not None:
            self.codeslayoutview.Dah()


    def endCharacter(self):
        character, self.currentCharacter = self.currentCharacter, []
        success, label = self.handleMorseCode(character)
        if self.codeslayoutview is not None:
            self.codeslayoutview.reset()
            if character and hasattr(self.codeslayoutview, 'showResult'):
                if success:
                    self.codeslayoutview.showResult(label, True)
                else:
                    self.codeslayoutview.showMessage(label, False)
            self.updateOutputState()
        if character:
            self.audio.confirm(success)

    def enableRepeatMode(self):
        self.repeaton = self.key_output.toggle_lock_mode()
        self.updateOutputState()

    def handleMorseCode(self, character):
        morse_code = ''.join(str(symbol) for symbol in character)
        if not morse_code:
            return False, ''
        try:
            items = self.layoutManager.get_active_layout().get('items', [])
            item = next((item for item in items if item.get('code') == morse_code), None)
            if item is None or '_action' not in item:
                return False, '无效码：' + morse_code.replace('1', '•').replace('2', '—')
            action = item['_action']
            label = action.getlabel()
            action.perform()
            logging.debug('Completed Morse action: %s', item.get('action'))
            return True, label or item.get('action', '')
        except Exception:
            logging.exception('Failed to perform Morse action')
            self.resetOutput()
            self.repeaton = False
            return False, '执行失败，请查看诊断日志'
        finally:
            self.updateOutputState()


class ChineseUiTranslator(QTranslator):
    # The bundled Qt Chinese catalog covers widget menus, but some versions
    # lack QPlatformTheme's standard dialog button translations.
    BUTTON_TEXT = {
        'OK': '确定', 'Save': '保存', 'Save All': '全部保存', 'Open': '打开',
        'Yes': '是', 'Yes to All': '全部是', 'No': '否', 'No to All': '全部否',
        'Abort': '中止', 'Retry': '重试', 'Ignore': '忽略', 'Close': '关闭',
        'Cancel': '取消', 'Discard': '放弃', 'Help': '帮助', 'Apply': '应用',
        'Reset': '重置', 'Restore Defaults': '恢复默认',
    }

    def translate(self, context, source_text, disambiguation=None, n=-1):
        if context in ('QPlatformTheme', 'QDialogButtonBox'):
            label = self.BUTTON_TEXT.get(source_text.replace('&', ''))
            if label is not None:
                return label
        return super().translate(context, source_text, disambiguation, n)


class CustomApplication(QApplication):
    def __init__(self, argv):
        QLocale.setDefault(QLocale(QLocale.Chinese, QLocale.China))
        super().__init__(argv)
        self.setApplicationName("摩斯输入")
        self.setQuitOnLastWindowClosed(False)
        self.qt_translator = ChineseUiTranslator(self)
        self.qt_translator.load("qt_zh_CN", QLibraryInfo.location(QLibraryInfo.TranslationsPath))
        self.installTranslator(self.qt_translator)
        self.theme_manager = ThemeManager(self)

    def notify(self, receiver, event):
        #logging.debug(f"Event: {event.type()}, Receiver: {receiver.__class__.__name__}")
        return super().notify(receiver, event)


if __name__ == '__main__':
    smoke_report = None
    if '--smoke-test' in sys.argv:
        smoke_report = sys.argv[sys.argv.index('--smoke-test') + 1]
    user_data_dir = str(bootstrap_assets(DEFAULT_CONFIG))
    from crash_diagnostics import install_diagnostics, log_qt_message
    install_diagnostics(user_data_dir)
    QtCore.qInstallMessageHandler(log_qt_message)
    app = CustomApplication(sys.argv)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        # At Windows login Explorer may still be starting. Qt automatically
        # registers a visible tray icon once the notification area is ready.
        logging.info('Waiting for the system tray to become available')

    QApplication.setQuitOnLastWindowClosed(False)

    # Initialize managers
    configmanager = ConfigManager(os.path.join(user_data_dir, "config.json"), default_config=DEFAULT_CONFIG)
    layoutmanager = LayoutManager(os.path.join(user_data_dir, "layouts.json"))

    # Create main window
    window = Window(layoutManager=layoutmanager, configManager=configmanager)

    # Now that we have the window, initialize actions that may require window reference
    actions = configmanager.initActions(window)
    layoutmanager.set_actions(actions)

    # Finish initializing the window if needed (after actions are available)
    window.postInit()

    if smoke_report:
        from frozen_smoke import verify_installation
        verify_installation(window, smoke_report)
    else:
        window.startDesktopIntegration()
        window.presentAtLaunch(startup=('--startup' in sys.argv or '/auto' in sys.argv))

    # Start the application event loop
    exit_code = app.exec_()
    window.shutdown()
    # Destroy Qt wrappers while QApplication and Python are still alive.
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    sys.exit(exit_code)
