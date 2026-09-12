# Standard library imports
import configparser
import json
import logging
import os
import sys
import platform
import threading
import time
from html import escape
from collections import OrderedDict
from enum import Enum
from threading import Thread

# Third-party imports
from PyQt5 import QtCore, QtMultimedia
from PyQt5.QtMultimedia import QAudioDeviceInfo, QAudio, QAudioFormat, QAudioOutput
from PyQt5.QtCore import QIODevice, QFile, QThread, pyqtSignal, QTimer, Qt, QObject, QLocale, QTranslator, QLibraryInfo
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QAction, QCheckBox, QComboBox, QDialog, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QRadioButton, QSystemTrayIcon, QVBoxLayout,
                             QWidget, QApplication, QMenu, QFileDialog, QStatusBar, QScrollArea)
from nava import play
import keyboard
import mouse
# Local application/library specific imports
import pressagio.callback
import pressagio
import icons_rc
from ui_theme import ThemeManager, THEME_COLORS
from keyboard_output import KeyboardOutput
from virtual_keyboard import VirtualKeyboardView

def get_user_data_dir(app_name="MorseWriter"):
    """
    Returns the appropriate directory for storing user data based on the OS and whether the app is frozen.
    """
    if hasattr(sys, 'frozen'):
        # If the application is frozen, use the appropriate platform-specific directory
        if platform.system() == 'Windows':
            return os.path.join('C:\\', 'Users', 'Public', 'Documents', 'Ace Centre', app_name, 'user_data')
        elif platform.system() == 'Darwin':
            return os.path.join(os.path.expanduser('~/Library/Application Support/'), app_name, 'user_data')
        else:
            return os.path.join(os.path.expanduser('~/.config/'), app_name, 'user_data')
    else:
        # Use a local directory when running in development
        return os.path.join(os.path.dirname(os.path.realpath(__file__)), 'user_data')


# Configure basic logger
logfile = os.path.join(get_user_data_dir(), "morsewriter-log.log")
logging.basicConfig(level=logging.DEBUG, filename=logfile, filemode='w',format='%(name)s - %(levelname)s - %(message)s')

# # If you want to the console
# logging.basicConfig(level=logging.DEBUG,format='%(name)s - %(levelname)s - %(message)s')

lastkeydowntime = -1

keystrokes_state = {}
currentX = 0
currentY = 0
pressingKey = False
typestate = None

# If configfile file is lost.. 
DEFAULT_CONFIG = {
  "theme": "system",
  "guide_layout": "desktop",
  "keylen": 1,
  "keyone": "SPACE",
  "keytwo": "ENTER",
  "keythree": "RCTRL",
  "maxDitTime": 350,  # It's better to store numbers as numbers, not strings
  "minLetterPause": 1000,
  "withsound": True,
  "SoundDit": "res/dit_sound.wav",
  "SoundDah": "res/dah_sound.wav",
  "SoundTyping": "res/typing_sound.wav",
  "debug": True,
  "off": False,
  "fontsizescale": 100,
  "upperchars": True,
  "autostart": False,
  "winxaxis": "left",
  "winyaxis": "top",
  "winposx": 10,
  "winposy": 10
}



class AudioDeviceSelector(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle('音频设备')
        self.layout = QVBoxLayout()

        self.label = QLabel('选择音频设备：')
        self.layout.addWidget(self.label)

        self.device_selector = QComboBox()
        self.list_available_devices()
        self.device_selector.currentIndexChanged.connect(self.device_changed)
        self.layout.addWidget(self.device_selector)

        self.test_audio_button = QPushButton('播放测试音')
        self.test_audio_button.clicked.connect(self.test_audio)
        self.layout.addWidget(self.test_audio_button)

        self.setLayout(self.layout)

        self.sound_file = None
        self.player = QtMultimedia.QMediaPlayer()
        self.selected_device = self.device_selector.currentData()

        icon = QIcon(':/morse-writer.ico')
        self.setWindowIcon(icon)

    def device_changed(self, index):
        self.selected_device = self.device_selector.itemData(index)
        print(f"Selected device audio device {index} : {self.selected_device.deviceName()}")

    def list_available_devices(self):
        default_device = QAudioDeviceInfo.defaultOutputDevice()
        self.device_selector.addItem("默认输出设备", default_device)

        for device in QAudioDeviceInfo.availableDevices(QAudio.AudioOutput):
            device_names = [self.device_selector.itemText(i) for i in range(self.device_selector.count())]
            if device.deviceName() != default_device.deviceName() and device.deviceName() not in device_names:
                self.device_selector.addItem(device.deviceName(), device)

    def play_audio(self, file):
        # check here if file exist
        if os.path.exists(file):
            url = QtCore.QUrl.fromLocalFile(QtCore.QDir.current().absoluteFilePath(file))
            self.player.setMedia(QtMultimedia.QMediaContent(url))
            self.player.play()

    def test_audio(self):
        self.play_audio("res/dah_sound.wav")

    def select_audio_file(self):
        file_dialog = QFileDialog()
        self.audio_file, _ = file_dialog.getOpenFileName(self, "选择音频文件", "", "音频文件 (*.wav)")
        if self.audio_file:
            print(f"Selected audio file: {self.audio_file} to play on device {self.selected_device.deviceName()}")
            self.play_audio(self.audio_file)


@staticmethod
def load_abbreviations(file_path):
    abbreviations = {}
    try:
        logging.debug(f"[TypeState] Trying to load abbreviations from file: {file_path}")
        with open(file_path, 'r') as f:
            for line in f:
                if line.strip():
                    abbr, expansion = line.strip().split('\t')
                    abbreviations[abbr] = expansion
    except Exception as e:
        logging.error(f"Failed to load abbreviations: {e}")
    return abbreviations


@staticmethod
def expand_abbreviation(keys, abbreviations):
    words = keys.split()
    if not words or not abbreviations:
        return None, None
    last_word = words[-1]

    if last_word in abbreviations:
        return abbreviations[last_word], len(last_word)
    else:
        return None,None

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
        "CODESET": {'label': '切换码表', 'key_code': 'unknown', 'character': None, 'arg': 9},
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
        self.config_file = config_file or os.path.join(user_data_dir, 'config.json')
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
                    # self.update_keystrokes(data) # Note:cause issue to save configuration
                    self.convert_types(data)
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
                # Mouse actions will use ActionLegacy
                actions[key.upper()] = lambda item, lbl=label, kc=key_code, char=character, a=arg, win=window: ActionLegacy(item, a, lbl, kc)
            else:
                # Correctly capture the loop variables using default values in lambda
                actions[key.upper()] = lambda item, win=window, lbl=label, kc=key_code, char=character, a=arg, tog=toggle_action: ActionKeyStroke(
                    {'label': lbl, 'key_code': kc, 'character': char, 'arg': a}, kc, tog, win)

        # Define special actions with correct lambda capturing
        actions["CHANGELAYOUT"] = lambda item, win=window: ChangeLayoutAction(item, win.changeLayout)
        actions["PREDICTION_SELECT"] = lambda item, win=window: PredictionSelectLayoutAction(
            item, get_predictions_func=win.getTypeStatePredictions, select_prediction_func=win.selectPrediction)

        # Assuming the action name is stored in item['action'] and matches keys in key_data
        actions["KEYSTROKE"] = lambda item, kd=self.key_data, win=window: ActionKeyStroke(
            item, kd[item['action'].upper()]['key_code'], win=win)

        actions["REPEATMODE"] = lambda item, win=window: RepeatOnAction(item, repeat_on_callback=win.enableRepeatMode)
        actions["SOUND"] = lambda item, win=window: CallbackAction(item, '提示音', win.toggleSound)
        actions["CODESET"] = lambda item, win=window: CallbackAction(item, '切换码表', win.cycleLayout)

        self.actions = actions
        return actions


class TypeState(pressagio.callback.Callback):
    def __init__ (self, abbreviations=None):
        self.text = ""
        self.predictions = None

        pressagioconfig_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "res",
                                            "morsewriter_pressagio.ini")
        logging.debug(f"[TypeState] Searching for pressagio config file with name: {pressagioconfig_file}")

        pressagioconfig = configparser.ConfigParser()
        pressagioconfig.read(pressagioconfig_file)

        database = pressagioconfig.get("Database", "database")
        logging.debug(f"[TypeState] Searching for database file: {database}")

        if pressagioconfig:
            try:
                self.presage = pressagio.Pressagio(self, pressagioconfig)
                logging.debug("[TypeState] Pressagio Initialized successfully")
            except Exception as e:
                logging.error(f"[TypeState] Pressagio Failed to Initialize with error={e}")

        self.abbreviations = abbreviations
        self.expanded_text = None
        self.keyLength = 0

    def past_stream (self):
        return self.text
    def future_stream (self):
        return self.text
    def pushchar (self, char):
        self.text += char
        self.predictions = None
        logging.debug(f"Updated TypeState text: {self.text}")
    def pushstr (self, str):
        self.text += str
        self.predictions = None
        logging.debug(f"Updated TypeState text: {self.text}")
    def popchar (self):
        self.text = self.text[:-1]
        self.predictions = None
    def getpredictions(self):
        logging.debug("[TypeState] Fetching predictions for text: {}".format(self.text))
        if self.predictions is None:
            try:
                self.predictions = self.presage.predict()
                logging.debug("[TypeState] Predictions fetched: {}".format(self.predictions))

            except Exception as e:
                logging.error(f"[TypeState] Failed to generate predictions: {str(e)}")
                self.predictions = []

        return self.predictions


    def get_abbreviation(self):
        logging.debug("[TypeState] Fetching abbreviation for text: {}".format(self.text))
        if self.text is not None:
            try:
                self.expanded_text, self.keyLength = expand_abbreviation(self.text, self.abbreviations)
                logging.debug("[TypeState] Abbreviation fetched: {}".format(self.expanded_text))

            except Exception as e:
                logging.error(f"[TypeState] Failed to get abbreviations: {str(e)}")
                self.expanded_text = None
                self.keyLength = 0

        return self.expanded_text, self.keyLength

class KeyListenerThread(QThread):
    keyEvent = pyqtSignal(str, bool, int)  # Emit key name and press/release status

    def __init__(self, configured_keys):
        super().__init__()
        self.configured_keys = configured_keys  # keys in the 'keyboard' library format
        self.keep_running = True  # Control running of the loop

    def run(self):
        # Check if the operating system is MacOS
        if platform.system() == 'Darwin':
            # If it is, only allow modifier keys
            allowed_keys = ['shift', 'ctrl', 'alt', 'cmd']
            self.configured_keys = [key for key in self.configured_keys if key in allowed_keys]

        unhooks = []
        try:
            for role, key in enumerate(self.configured_keys):
                # Bind the role to the hook: event names can change with Shift
                # or use a different alias (e.g. "shift" vs "left shift").
                callback = lambda event, key=key, role=role: self.on_key_event(event, key, role)
                unhooks.append(keyboard.hook_key(key, callback, suppress=True))

            while self.keep_running:
                time.sleep(0.1)
        finally:
            # Clean up even if startup fails or stop() races with registration.
            for unhook in reversed(unhooks):
                unhook()

    def on_key_event(self, event, key, role):
        if not self.keep_running:
            return True
        # keyboard.hook_key also matches keypad scan codes and, on Windows,
        # both Ctrl keys. Preserve keys outside the selected physical input.
        if event.is_keypad:
            return True
        sided_names = {
            'left ctrl': ('left ctrl', 'ctrl'),
            'right ctrl': ('right ctrl',),
            'left shift': ('left shift', 'shift'),
            'right shift': ('right shift',),
        }
        if key in sided_names and event.name not in sided_names[key]:
            return True
        try:
            self.keyEvent.emit(key, event.event_type == keyboard.KEY_DOWN, role)
        except Exception as e:
            logging.warning(f"[KeyListenerThread] Error handling key event: {e}")
            return True
        return False  # Only the active Morse input keys are consumed.

    def stop(self):
        self.keep_running = False  # Signal the loop to stop
        self.wait()  # Wait for the thread to finish


class KeyCombinationListener(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_modifiers = 0
        self.current_key = 0
        logging.debug(f"[KeyCombinationListener __init__]")

    def keyPressEvent(self, event):
        self.current_modifiers |= int(event.modifiers())
        self.current_key = event.key()

        if (self.current_modifiers & Qt.CTRL and
            self.current_modifiers & Qt.SHIFT and
            self.current_key == Qt.Key_P):
            self.resetState()
            logging.debug("[KeyCombinationListener] \"Ctrl + Shift + P\" detected Escaping Morse Mode")
            return True
        else:
            self.resetState()
            return False

    def keyReleaseEvent(self, event):
        self.resetState()

    def resetState(self):
        self.current_modifiers = 0
        self.current_key = 0


class PressagioCallback(pressagio.callback.Callback):
    def __init__(self, buffer):
        super().__init__()
        self.buffer = buffer

    def past_stream(self):
        return self.buffer

    def future_stream(self):
        return ""

class LayoutManager:
    def __init__(self, layout_file):
        self.layout_file = layout_file
        self.layouts = {}
        self.active_layout_name = None
        self.main_layout_name = None
        self.load_layouts()

    def load_layouts(self):
        """Loads layout data from a JSON file without assigning actions."""
        try:
            with open(self.layout_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.layouts = {k: v for k, v in data['layouts'].items()}
            self.main_layout_name = data.get('mainlayout')
            self.active_layout_name = data.get('mainlayout')
            if self.active_layout_name not in self.layouts:
                raise ValueError("No valid main layout found in the layout file.")
        except FileNotFoundError:
            raise Exception(f"Layout file {self.layout_file} not found.")
        except json.JSONDecodeError:
            raise Exception("Error decoding JSON from the layout file.")

    def set_actions(self, actions):
        """Integrates actions with the layout items loaded from the layout file."""
        for layout_name, layout in self.layouts.items():
            if 'items' in layout:
                for item in layout['items']:
                    action_name = item.get('action')
                    if action_name in actions:
                        item['_action'] = actions[action_name](item)
                    else:
                        item['_action'] = None
                        logging.warning(f"No action found for {action_name} in layout {layout_name}")

    def set_active(self, layout_name):
        """Sets the active layout by name."""
        if layout_name in self.layouts:
            self.active_layout_name = layout_name
            logging.info(f"Active layout set to {layout_name}")
        else:
            raise ValueError("Specified layout does not exist.")

    def get_active_layout(self):
        """Returns the currently active layout."""
        if self.active_layout_name:
            return self.layouts[self.active_layout_name]
        else:
            raise ValueError("No active layout set.")

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


def getPossibleCombos(currentCharacter):
    x = ""
    for i in currentCharacter:
        x += str(i)
    possibleactions = []
    for action in normalmapping:
        if (len(action) >= len(x) and action[:len(x)] == x):
            possibleactions.append(action)
    logging.debug("possible: %s", str(possibleactions))


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


class ActionLegacy (Action):
    def __init__(self, item, arg, label, key=None):
        super(ActionLegacy, self).__init__(item)  # Pass required parameters
        # Additional initialization for ActionLegacy
        self.arg = arg
        self.label = label
        self.key = key

    def getlabel (self):
        return self.label


    def perform(self):
        logging.debug(f"[ActionLegacy] Key to press/release: {self.key}, type: {type(self.key)}")
        action_map = {
            'MOUSEUP5': lambda: moveMouse(0, -5),
            'MOUSEDOWN5': lambda: moveMouse(0, 5),
            'MOUSELEFT5': lambda: moveMouse(-5, 0),
            'MOUSERIGHT5': lambda: moveMouse(5, 0),
            'MOUSEUPLEFT5': lambda: moveMouse(-5, -5),
            'MOUSEUPRIGHT5': lambda: moveMouse(5, -5),
            'MOUSEDOWNLEFT5': lambda: moveMouse(-5, 5),
            'MOUSEDOWNRIGHT5': lambda: moveMouse(5, 5),
            'MOUSEUP40': lambda: moveMouse(0, -40),
            'MOUSEDOWN40': lambda: moveMouse(0, 40),
            'MOUSELEFT40': lambda: moveMouse(-40, 0),
            'MOUSERIGHT40': lambda: moveMouse(40, 0),
            'MOUSEUPLEFT40': lambda: moveMouse(-40, -40),
            'MOUSEUPRIGHT40': lambda: moveMouse(40, -40),
            'MOUSEDOWNLEFT40': lambda: moveMouse(-40, 40),
            'MOUSEDOWNRIGHT40': lambda: moveMouse(40, 40),
            'MOUSEUP250': lambda: moveMouse(0, -250),
            'MOUSEDOWN250': lambda: moveMouse(0, 250),
            'MOUSELEFT250': lambda: moveMouse(-250, 0),
            'MOUSERIGHT250': lambda: moveMouse(250, 0),
            'MOUSEUPLEFT250': lambda: moveMouse(-250, -250),
            'MOUSEUPRIGHT250': lambda: moveMouse(250, -250),
            'MOUSEDOWNLEFT250': lambda: moveMouse(-250, 250),
            'MOUSEDOWNRIGHT250': lambda: moveMouse(250, 250),
            'MOUSECLICKLEFT': lambda: clickMouse(mouse.LEFT, 'click'),
            'MOUSECLICKRIGHT': lambda: clickMouse(mouse.RIGHT, 'click'),
            'MOUSEDBLCLICKLEFT': lambda: mouse.double_click(button=mouse.LEFT),
            'MOUSEDBLCLICKRIGHT': lambda: mouse.double_click(button=mouse.RIGHT),
            'MOUSECLKHLDLEFT': lambda: clickMouse(mouse.LEFT, 'press'),
            'MOUSECLKHLDRIGHT': lambda: clickMouse(mouse.RIGHT, 'press'),
            'MOUSERELEASEHOLD': lambda: (clickMouse(mouse.LEFT, 'release'), clickMouse(mouse.RIGHT, 'release'))
        }

        # Execute the mapped function based on self.key if exists
        if self.key and self.key in action_map:
            action_map[self.key]()
        else:
            logging.debug(f"[ActionLegacy-perform] No action defined for key: {self.key}")


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
        logging.debug(f"[ActionKeyStroke] Key to press/release: {self.key}, type: {type(self.key)}")
        try:
            text = self.window.key_output.send(
                self.key, self.item.get('character'), modifier=self.toggle_action)
            state = self.window.typestate
            if state is None or text is None:
                return
            if text == '\b':
                state.popchar()
                return
            state.pushstr(text)
            # Expand complete words only on the dedicated typing page. The main
            # keyboard and short numeric codes must emit their advertised keys.
            if (self.window.layoutManager.active_layout_name != 'typing' or text != ' '
                    or len(state.text) < 2 or state.text[-2].isspace()):
                return
            abbreviation, keylength = state.get_abbreviation()
            if abbreviation is not None:
                self.window.key_output.reset()
                self.window.repeaton = False
                for _ in range(keylength + 1):
                    self.window.key_output.send('backspace', '\b')
                    state.popchar()
                state.pushstr(self.window.key_output.send_text(abbreviation + ' '))
        except Exception as e:
            logging.error(f"[ActionKeyStroke] Error during key press/release: {e}")
            raise


class ChangeLayoutAction(Action):
    def __init__(self, item, change_layout_callback):
        super().__init__(item)
        self.change_layout_callback = change_layout_callback
        self.layout_name = item['target']

    def perform(self):
        # Now call the callback with the stored layout name
        if callable(self.change_layout_callback):
            self.change_layout_callback(self.layout_name)
        else:
            raise ValueError("Change Layout callback is not callable")

#     def __init__(self, item, window):
#         super().__init__(item)
#         self.window = window
# 
#     def perform(self):
#         target_layout = self.item.get('target')
#         if target_layout and target_layout in self.window.layoutManager.layouts:
#             # Use the layout name to set the active layout
#             self.window.layoutManager.set_active(target_layout)
#             self.codeslayoutview.changeLayoutSignal.emit()
#         else:
#             raise ValueError(f"Layout '{target_layout}' not found")


class PredictionSelectLayoutAction(Action):
    def __init__(self, item, get_predictions_func, select_prediction_func):
        super().__init__(item)
        self.get_predictions_func = get_predictions_func
        self.select_prediction_func = select_prediction_func

    def getlabel(self):
        predictions = self.get_predictions_func()
        target = self.item.get('target', -1)
        if 0 <= target < len(predictions):
            return predictions[target]
        return ""

    def perform(self):
        self.select_prediction_func(self.item.get('target', -1))


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
        self.typestate = None
        self.key_output = KeyboardOutput()
        self.actions = {}
        self.keystrokes = []
        self.keystrokemap = {}
        logging.info(f"Window initialized with layout: {self.layoutManager.main_layout_name}")

        self.listenerThread = None
        self.currentCharacter = []
        self.previousCharacter = []
        self.lastKeyDownTime = None
        self.endCharacterTimer = None
        self.inputDisabled = False
        self.codeslayoutview = None
        self.fast_morse_mode_timer = None
        self.repeat_character_timer = None

        self.repeaton = False

        self.audioSelector = AudioDeviceSelector()
        app = QApplication.instance()
        app.theme_manager.set_mode(self.config.get('theme', 'system'))
        app.theme_manager.themeChanged.connect(self.refreshTheme)

    def load_default_config(self):
        return DEFAULT_CONFIG.copy()

    def init(self):
        self.key_output.reset()
        self.currentCharacter = []
        self.previousCharacter = []
        self.repeaton = False

        logging.debug("[Window init] Setting active layout to: %s", self.layoutManager.main_layout_name)
        preferred = self.config.get('guide_layout', self.layoutManager.main_layout_name)
        if preferred not in self.layoutManager.layouts:
            preferred = self.layoutManager.main_layout_name
        self.layoutManager.set_active(preferred)
        logging.debug("[Window init] Active layout successfully set to: %s", self.layoutManager.active_layout_name)
        # Check for specific layout types that may require special handling
        if self.layoutManager.get_active_layout().get('supports_prediction', False):
            self.abbreviations = load_abbreviations(os.path.join(user_data_dir,"abbreviations_en.txt"))
            self.typestate = TypeState(self.abbreviations)
        else:
            self.typestate = None
        logging.debug(f"[Window init] layout that is active is: {self.layoutManager.main_layout_name} ")
        self.showCodeView()
        logging.debug(f"[Window init] Initial visibility status: {self.codeslayoutview.isVisible()}")

    def postInit(self):
        # Initialize components that depend on actions being available
        self.actions = self.configManager.actions
        self.keystrokes = self.configManager.keystrokes
        self.keystrokemap = self.configManager.keystrokemap
        #self.codeslayoutview = CodesLayoutViewWidget(self.layoutManager.get_active_layout(), self.config, self)
        self.createIconGroupBox()
        self.createActions()
        self.createTrayIcon()
        self.trayIcon.activated.connect(self.iconActivated)
        self.GOButton.clicked.connect(self.goForIt)
        self.SaveButton.clicked.connect(self.saveSettings)
        self.DeviceButton.clicked.connect(self.changeAudioDevice)
        self.withSound.clicked.connect(self.updateAudioProperties)
        mainLayout = QVBoxLayout()
        mainLayout.addWidget(self.iconGroupBox)
        self.setLayout(mainLayout)
        self.setIcon()
        self.trayIcon.show()
        self.setWindowTitle("摩斯输入设置")
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.resize(400, 300)


    def get_configured_keys(self):
        key_codes = []
        default_keys = {'keyone': 'SPACE', 'keytwo': 'ENTER', 'keythree': 'RCTRL'}
        key_count = int(self.config.get('keylen', 1))

        for key in ['keyone', 'keytwo', 'keythree'][:key_count]:
            config_key = self.config.get(key, default_keys[key])
            try:
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
        if self.config.get('off', False):
            return
        key_codes = self.get_configured_keys()
        logging.debug(f"[Window startKeyListener] Configured keys: {key_codes}")
        if not self.listenerThread:
            self.listenerThread = KeyListenerThread(configured_keys=key_codes)
            self.listenerThread.keyEvent.connect(self.handle_key_event)
            self.listenerThread.start()


    def updateAudioProperties(self):
        if self.withSound.isChecked():
            self.iconComboBoxSoundDit.setEnabled(True)
            self.iconComboBoxSoundDah.setEnabled(True)
        else:
            self.iconComboBoxSoundDit.setEnabled(False)
            self.iconComboBoxSoundDah.setEnabled(False)

    def changeLayout(self, layout_name):
        if layout_name not in self.layoutManager.layouts:
            raise ValueError(f"Unknown layout: {layout_name}")
        for name in ('endCharacterTimer', 'fast_morse_mode_timer'):
            timer = getattr(self, name)
            if timer is not None:
                timer.stop()
                setattr(self, name, None)
        self.currentCharacter = []
        self.lastKeyDownTime = None
        self.layoutManager.set_active(layout_name)
        if self.codeslayoutview is not None:
            self.codeslayoutview.hide()
            self.codeslayoutview.deleteLater()
        if self.typestate is None and self.layoutManager.get_active_layout().get('supports_prediction', False):
            self.abbreviations = load_abbreviations(os.path.join(get_user_data_dir(), 'abbreviations_en.txt'))
            self.typestate = TypeState(self.abbreviations)
        self.showCodeView()

    def showCodeView(self):
        view_class = VirtualKeyboardView if self.layoutManager.active_layout_name == 'desktop' else CodesLayoutViewWidget
        view = view_class(self.layoutManager.get_active_layout(), self.config)
        self.codeslayoutview = view
        view.setAvailableLayouts(self.layoutManager.layouts, self.layoutManager.active_layout_name)
        view.changeLayoutSignal.connect(self.changeLayout)
        view.settingsRequested.connect(self.backToSettings)
        self.updateOutputState()
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

    def updateOutputState(self):
        if self.codeslayoutview is not None:
            self.codeslayoutview.setOutputState(self.key_output.held_modifiers, self.repeaton)

    def toggleSound(self):
        self.config['withsound'] = not self.config['withsound']
        self.withSound.setChecked(self.config['withsound'])
        self.updateAudioProperties()
        self.updateOutputState()

    def cycleLayout(self):
        names = list(self.layoutManager.layouts)
        current = names.index(self.layoutManager.active_layout_name)
        self.changeLayout(names[(current + 1) % len(names)])

    def selectPrediction(self, target):
        if self.typestate is None:
            return
        predictions = self.typestate.getpredictions()
        if not 0 <= target < len(predictions):
            return
        self.key_output.reset()
        self.repeaton = False
        suffix = self.typestate.text.split()[-1] if self.typestate.text and not self.typestate.text[-1].isspace() else ''
        for _ in suffix:
            self.key_output.send('backspace', '\b')
            self.typestate.popchar()
        self.typestate.pushstr(self.key_output.send_text(predictions[target] + ' '))



    def getTypeStatePredictions(self):
        logging.debug(f"[Window] getTypeStatePredictions")
        if self.typestate:
            return self.typestate.getpredictions()
        return []

    def collect_config(self):
        config = {
            'theme': self.themeComboBox.currentData(),
            'guide_layout': self.guideLayoutComboBox.currentData(),
            'keylen': self.keySelectionRadioOneKey.isChecked() and 1 or self.keySelectionRadioTwoKey.isChecked() and 2 or 3,
            'keyone': self.iconComboBoxKeyOne.itemData(self.iconComboBoxKeyOne.currentIndex()),
            'keytwo': self.iconComboBoxKeyTwo.itemData(self.iconComboBoxKeyTwo.currentIndex()),
            'keythree': self.iconComboBoxKeyThree.itemData(self.iconComboBoxKeyThree.currentIndex()),
            'maxDitTime': float(self.maxDitTimeEdit.text()),
            'minLetterPause': float(self.minLetterPauseEdit.text()),
            'withsound': self.withSound.isChecked(),
            'SoundDit': self.iconComboBoxSoundDit.itemData(self.iconComboBoxSoundDit.currentIndex()),
            'SoundDah': self.iconComboBoxSoundDah.itemData(self.iconComboBoxSoundDah.currentIndex()),
            'SoundTyping': self.iconComboBoxSoundTyping.itemData(self.iconComboBoxSoundTyping.currentIndex()),
            'debug': self.withDebug.isChecked(),
            'off': False,
            'fontsizescale': float(self.fontSizeScaleEdit.text()),
            'upperchars': self.upperCharsCheck.isChecked(),
            'autostart': self.autostartCheckbox.isChecked(),
            'winxaxis': "left" if self.keyWinPosXLeftRadio.isChecked() else "right",
            'winyaxis': "top" if self.keyWinPosYTopRadio.isChecked() else "bottom",
            'winposx': self.keyWinPosXEdit.text(),
            'winposy': self.keyWinPosYEdit.text(),
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

        self.iconComboBoxKeyOne.currentData()
        if self.trayIcon.isVisible():
            QMessageBox.information(self, "摩斯输入",
                                    "程序将在系统托盘中运行。点击窗口的 × 可最小化，输入会继续运行。点击托盘图标可恢复窗口；需要关闭程序时，请在托盘菜单中选择<b>退出</b>。")
            self.hide()
        self.config = self.collect_config()
        self.onOffAction.setText("暂停输入")
        self.init()
        if not self.listenerThread:
            self.startKeyListener()

    def start (self):
        self.init()
        self.startKeyListener()

    def closeEvent(self, event):
        event.ignore()
        self.showMinimized()

    def quitApplication(self):
        self.stopIt()
        self.audioSelector.hide()
        self.hide()
        self.trayIcon.hide()
        QApplication.instance().quit()

    def setIcon(self):
        icon = QIcon(':/morse-writer.ico')
        self.trayIcon.setIcon(icon)
        self.setWindowIcon(icon)

    def iconActivated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.showCurrentWindow()

    def showCurrentWindow(self):
        target = self.codeslayoutview if self.codeslayoutview is not None else self
        target.showNormal()
        target.raise_()
        target.activateWindow()

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

        maxDitTimeLabel = QLabel("点划分界时长（毫秒）：")
        self.maxDitTimeEdit = QLineEdit(str(self.config.get("maxDitTime", "350")))
        minLetterPauseLabel = QLabel("字符间隔（毫秒）：")
        self.minLetterPauseEdit = QLineEdit(str(self.config.get("minLetterPause", "1000")))
        TimingsLayout = QGridLayout()
        TimingsLayout.addWidget(maxDitTimeLabel, 0, 0)
        TimingsLayout.addWidget(self.maxDitTimeEdit, 0, 1, 1, 4)
        TimingsLayout.addWidget(minLetterPauseLabel, 1, 0)
        TimingsLayout.addWidget(self.minLetterPauseEdit, 1, 1, 2, 4)
        TimingsLayout.setRowStretch(4, 1)
        inputSettingsLayout.addLayout(TimingsLayout)

        self.withDebug = QCheckBox("启用调试")
        self.withDebug.setChecked(self.config.get("debug", False))
        inputSettingsLayout.addWidget(self.withDebug)

        self.withSound = QCheckBox("播放提示音")
        self.withSound.setChecked(self.config.get("withsound", True))
        inputSettingsLayout.addWidget(self.withSound)

        fontSizeScaleLabel = QLabel("字号缩放（%）：")
        self.fontSizeScaleEdit = QLineEdit(str(self.config.get("fontsizescale", "100")))
        viewSettingSec = QGridLayout()
        viewSettingSec.addWidget(fontSizeScaleLabel, 0, 0)
        viewSettingSec.addWidget(self.fontSizeScaleEdit, 0, 1, 1, 2)
        self.upperCharsCheck = QCheckBox("字母大写显示")
        self.upperCharsCheck.setChecked(self.config.get("upperchars", True))
        viewSettingSec.addWidget(self.upperCharsCheck, 0, 3)
        viewSettingSec.setRowStretch(4, 1)
        inputSettingsLayout.addLayout(viewSettingSec)

        appearance = QGridLayout()
        appearance.addWidget(QLabel('界面主题：'), 0, 0)
        self.themeComboBox = QComboBox()
        for label, mode in (('跟随系统', 'system'), ('浅色', 'light'), ('深色', 'dark')):
            self.themeComboBox.addItem(label, mode)
        self.themeComboBox.setCurrentIndex(max(0, self.themeComboBox.findData(self.config.get('theme', 'system'))))
        self.themeComboBox.currentIndexChanged.connect(self.changeTheme)
        appearance.addWidget(self.themeComboBox, 0, 1)
        appearance.addWidget(QLabel('输入面板：'), 1, 0)
        self.guideLayoutComboBox = QComboBox()
        names = {'desktop': '键盘与鼠标（统一面板）', 'main': '兼容 · 主键盘',
                 'typing': '兼容 · 字母与候选', 'mouse': '兼容 · 鼠标短码', 'number': '兼容 · 数字短码'}
        for name in ('desktop', 'main', 'typing', 'mouse', 'number'):
            if name in self.layoutManager.layouts:
                self.guideLayoutComboBox.addItem(names[name], name)
        self.guideLayoutComboBox.setCurrentIndex(max(0, self.guideLayoutComboBox.findData(self.config.get('guide_layout', 'desktop'))))
        self.guideLayoutComboBox.setToolTip('统一面板中可直接输入键盘与鼠标编码；兼容选项保留旧版短码。')
        appearance.addWidget(self.guideLayoutComboBox, 1, 1)
        inputSettingsLayout.addLayout(appearance)

        self.iconComboBoxSoundDit = self.mkKeyStrokeComboBox([
                ["点音", "res/dit_sound.wav"],  # Ensure the path is correct
                ["默认", "res/dit_sound.wav"]  # Optional: default sound path
            ], self.config.get('SoundDit', "res/dit_sound.wav"))

        self.iconComboBoxSoundDah = self.mkKeyStrokeComboBox([
            ["划音", "res/dah_sound.wav"],  # Ensure the path is correct
            ["默认", "res/dah_sound.wav"]  # Optional: default sound path
        ], self.config.get('SoundDah', "res/dah_sound.wav"))

        self.iconComboBoxSoundTyping = self.mkKeyStrokeComboBox([
            ["输入音", "res/typing_sound.wav"],
            ["默认", "res/typing_sound.wav"]
        ], self.config.get('SoundTyping', "res/typing_sound.wav"))


        DitSoundLabel = QLabel("点音：")
        DahSoundLabel = QLabel("划音：")
        TypingSoundLabel = QLabel("输入音：")
        SoundConfigLayout = QGridLayout()
        SoundConfigLayout.addWidget(DitSoundLabel, 0, 0)
        SoundConfigLayout.addWidget(self.iconComboBoxSoundDit, 0, 1, 1, 4)
        SoundConfigLayout.addWidget(DahSoundLabel, 1, 0)
        SoundConfigLayout.addWidget(self.iconComboBoxSoundDah, 1, 1, 1, 4)
        SoundConfigLayout.addWidget(TypingSoundLabel, 2, 0)
        SoundConfigLayout.addWidget(self.iconComboBoxSoundTyping, 2, 1, 1, 4)

        self.autostartCheckbox = QCheckBox("启动后自动开始输入")
        self.autostartCheckbox.setChecked(self.config.get("autostart", True))
        inputSettingsLayout.addWidget(self.autostartCheckbox)

        # Add Fast Morse Mode checkbox
        self.fastMorseModeCheckbox = QCheckBox("快速摩斯模式")
        self.fastMorseModeCheckbox.setChecked(self.config.get("fastMorseMode", False))
        inputSettingsLayout.addWidget(self.fastMorseModeCheckbox)

        self.updateFastMorseModeAvailability()  # Initialize the state based on the current key mode

        inputSettingsLayout.addLayout(SoundConfigLayout)

        inputRadioGroup = QGroupBox("码表水平位置（像素）")
        posAxisLayout = QHBoxLayout()
        self.keyWinPosXLeftRadio = QRadioButton("距左侧")
        self.keyWinPosXRightRadio = QRadioButton("距右侧")
        if self.config.get("winxaxis", "left") == "left":
            self.keyWinPosXLeftRadio.setChecked(True)
        else:
            self.keyWinPosXRightRadio.setChecked(True)
        posAxisLayout.addWidget(self.keyWinPosXLeftRadio)
        posAxisLayout.addWidget(self.keyWinPosXRightRadio)
        self.keyWinPosXEdit = QLineEdit(str(self.config.get("winposx", "10")))
        inputRadioGroup.setLayout(posAxisLayout)
        inputSettingsLayout.addWidget(inputRadioGroup)
        inputSettingsLayout.addWidget(self.keyWinPosXEdit)

        inputRadioGroup = QGroupBox("码表垂直位置（像素）")
        posAxisLayout = QHBoxLayout()
        self.keyWinPosYTopRadio = QRadioButton("距顶部")
        self.keyWinPosYBottomRadio = QRadioButton("距底部")
        if self.config.get("winyaxis", "top") == "top":
            self.keyWinPosYTopRadio.setChecked(True)
        else:
            self.keyWinPosYBottomRadio.setChecked(True)
        posAxisLayout.addWidget(self.keyWinPosYTopRadio)
        posAxisLayout.addWidget(self.keyWinPosYBottomRadio)
        self.keyWinPosYEdit = QLineEdit(str(self.config.get("winposy", "10")))
        inputRadioGroup.setLayout(posAxisLayout)
        inputSettingsLayout.addWidget(inputRadioGroup)
        inputSettingsLayout.addWidget(self.keyWinPosYEdit)

        self.DeviceButton = QPushButton("音频设备")
        self.SaveButton = QPushButton("保存设置")
        self.GOButton = QPushButton("开始输入")
        buttonsSec = QHBoxLayout()
        buttonsSec.addWidget(self.DeviceButton)
        buttonsSec.addWidget(self.SaveButton)
        buttonsSec.addWidget(self.GOButton)
        inputSettingsLayout.addLayout(buttonsSec)

        self.iconGroupBox.setLayout(inputSettingsLayout)

    def updateFastMorseModeAvailability(self):
        """
        Enable or disable Fast Morse Mode based on the selected key mode.
        """
        if self.keySelectionRadioOneKey.isChecked():
            self.fastMorseModeCheckbox.setEnabled(False)
            self.fastMorseModeCheckbox.setChecked(False)
        else:
            self.fastMorseModeCheckbox.setEnabled(True)

    def saveSettings (self):
        self.config = self.collect_config()
        self.configManager.save_config(self.config)

    def changeAudioDevice(self):
        self.audioSelector.show()

    def toggleOnOff(self):
        if self.codeslayoutview is None:
            return
        self.config['off'] = not self.config.get('off', False)
        self.onOffAction.setText("继续输入" if self.config['off'] else "暂停输入")
        if self.config['off']:
            self.stopKeyListener()
        else:
            self.startKeyListener()
        self.updateOutputState()

    def stopKeyListener(self):
        if self.listenerThread is not None:
            self.listenerThread.stop()
            self.listenerThread = None
        for name in ('endCharacterTimer', 'fast_morse_mode_timer', 'repeat_character_timer'):
            timer = getattr(self, name)
            if timer is not None:
                timer.stop()
                setattr(self, name, None)
        self.currentCharacter = []
        self.lastKeyDownTime = None
        self.repeaton = False
        self.key_output.reset()
        if self.codeslayoutview is not None:
            self.codeslayoutview.reset()
            self.updateOutputState()

    def stopIt(self):
        logging.debug("Stopping components...")
        self.stopKeyListener()
        if self.codeslayoutview is not None:
            self.codeslayoutview.hide()
            self.codeslayoutview = None
        logging.debug("All components stopped.")

    def backToSettings (self):
        self.showNormal()
        self.stopIt()

    def onOpenSettings (self):
        self.backToSettings()

    def createActions(self):
        self.showWindowAction = QAction("显示窗口", self, triggered=self.showCurrentWindow)
        self.onOffAction = QAction("继续输入" if self.config.get('off', False) else "暂停输入", self, triggered=self.toggleOnOff)
        self.onOpenSettingsAction = QAction("打开设置", self, triggered=self.onOpenSettings)
        self.quitAction = QAction("退出", self, triggered=self.quitApplication)

    def createTrayIcon(self):
        self.trayIconMenu = QMenu(self)
        self.trayIconMenu.addAction(self.showWindowAction)
        self.trayIconMenu.addAction(self.onOffAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.onOpenSettingsAction)
        self.trayIconMenu.addSeparator()
        self.trayIconMenu.addAction(self.quitAction)
        self.trayIcon = QSystemTrayIcon(self)
        self.trayIcon.setToolTip("摩斯输入")
        self.trayIcon.setContextMenu(self.trayIconMenu)

    def handle_key_event(self, key, is_press, role):
        if self.listenerThread is None or self.config.get('off', False):
            return  # Ignore queued events after pausing or returning to settings.
        # logging.debug(f"[handle_key_event] t={key}, Pressed={is_press}")
        try:
            if is_press:
                self.on_press(key, role)
            else:
                self.on_release(key, role)
        except Exception as e:
            logging.warning(f"[handle_key_event] Error handling key event: {e}")


    def on_press(self, key, role):
        try:
            if self.repeat_character_timer:
                self.repeat_character_timer.stop()
                self.repeat_character_timer = None

            # Handle disable toggle (adapt keys according to your config)
            if self.check_disable_combination(key):
                self.inputDisabled = not self.inputDisabled
                return

            if self.inputDisabled:
                return  # Ignore input if disabled

            # Prevent processing if key is already considered 'down'
            if self.lastKeyDownTime is not None:
                return

            # Start timing the key press
            self.lastKeyDownTime = time.time()
            logging.debug(f"[Window on_press] Key pressed: {key}")

            if self.config.get('fastMorseMode', False) and not self.keySelectionRadioOneKey.isChecked():
                self.fast_morse_mode_timer = QTimer(self)
                self.fast_morse_mode_timer.timeout.connect(lambda: self.repeat_key(key, role))
                self.fast_morse_mode_timer.start(100)  # Adjust the interval as needed

            if not self.keySelectionRadioOneKey.isChecked():
                # Check for dit or dah or end based on role
                if role == 0:
                    self.addDit()
                elif role == 1:
                    self.addDah()
                elif role == 2:
                    self.endCharacter()

        except Exception as e:
            logging.warning(f"[on_press] Error on key press: {e}")

    def repeat_key(self, key, role):
        if role == 0:
            self.addDit()
        elif role == 1:
            self.addDah()
        elif role == 2:
            self.endCharacter()


    def check_disable_combination(self, key):
        # Example logic, replace with actual keys and states
        return key == 'P' and self.key_state['CTRL'] and self.key_state['SHIFT']

    def on_release(self, key, role):
        try:
            if self.fast_morse_mode_timer:
                self.fast_morse_mode_timer.stop()
                self.fast_morse_mode_timer = None

            if self.lastKeyDownTime is not None:
                duration = (time.time() - self.lastKeyDownTime) * 1000  # Duration in milliseconds
                self.lastKeyDownTime = None  # Reset key down time

                if self.keySelectionRadioOneKey.isChecked():
                    # Check for dit or dah based on duration
                    maxDitTime = float(self.config.get('maxDitTime', 350))
                    if duration < maxDitTime:
                        self.addDit()
                    else:
                        self.addDah()

                if self.keySelectionRadioOneKey.isChecked() or self.keySelectionRadioTwoKey.isChecked():
                    # Start timer for end character sequence
                    self.startEndCharacterTimer()

                logging.debug(f"[Window on_release] Key released: {key}, duration: {duration}ms")

        except Exception as e:
            logging.warning(f"[on_release] Error on key release: {e}")


    def addDit(self):
        self.currentCharacter.append(1)
        if self.config['withsound']:
            # play("res/dit_sound.wav") #nava
            self.audioSelector.play_audio("res/dit_sound.wav")
        self.codeslayoutview.Dit()

    def addDah(self):
        self.currentCharacter.append(2)
        if self.config['withsound']:
            # play("res/dah_sound.wav") #nava
            self.audioSelector.play_audio("res/dah_sound.wav")
        self.codeslayoutview.Dah()


    def startEndCharacterTimer(self):
        if self.endCharacterTimer is not None:
            self.endCharacterTimer.stop()  # Stop existing timer
        self.endCharacterTimer = QTimer()
        self.endCharacterTimer.setSingleShot(True)
        self.endCharacterTimer.timeout.connect(self.endCharacter)
        self.endCharacterTimer.start(int(self.config['minLetterPause']))  # Configure delay from settings
        logging.debug(f"[startEndCharacter] Timer restarted with a delay of {self.config['minLetterPause']} ms")


    def endCharacter(self):
        if self.endCharacterTimer is not None:
            self.endCharacterTimer.stop()
            self.endCharacterTimer = None
        character = self.currentCharacter
        self.currentCharacter = []
        self.handleMorseCode(character)
        if self.codeslayoutview is not None:
            self.codeslayoutview.reset()
            self.updateOutputState()

    def enableRepeatMode(self):
        self.repeaton = self.key_output.toggle_lock_mode()
        self.updateOutputState()

    def handleMorseCode(self, character):
        morse_code = "".join(str(char) for char in character)
        if morse_code == "":
            logging.warning(f"[handleMorseCode] No action found for Morse code: {morse_code}")
            return

        try:
            active_layout = self.layoutManager.get_active_layout()
            items = active_layout.get('items', [])
            item = next((item for item in items if item.get('code') == morse_code), None)

            if item and '_action' in item:
                action = item['_action']
                if hasattr(action, 'perform') and callable(action.perform):
                    action.perform()
                    logging.info(f"[handleMorseCode] Action performed for Morse code: {morse_code}")
                    if self.config['withsound']:
                        # play(self.config.get('SoundTyping', 'res/typing_sound.wav'))  # Play typing sound
                        self.audioSelector.play_audio(self.config.get('SoundTyping', 'res/typing_sound.wav'))
                else:
                    logging.error(
                        f"[handleMorseCode] '_action' does not have a callable 'perform' method for Morse code: {morse_code}")
            else:
                logging.warning(f"[handleMorseCode] No action found for Morse code: {morse_code}")
        except Exception as e:
            logging.error(f"[handleMorseCode] Failed to perform action for Morse code: {morse_code}. Error: {e}")
            self.key_output.reset()
            self.repeaton = False
        finally:
            self.updateOutputState()

class CodeRepresentation(QWidget):
    def __init__(self, parent, code, item, c1, config):
        super(CodeRepresentation, self).__init__(None)
        self.config = config
        #logging.debug("CodeRepresentation - Item: %s", item)
        #logging.debug("CodeRepresentation - Config: %s", config)
        vlayout = QVBoxLayout()
        self.item = item
        self.character = QLabel(self.item['_action'].getlabel())
        self.character.setGeometry(10, 10, 10, 10)
        self.character.setContentsMargins(0, 0, 0, 0)
        self.character.setAlignment(Qt.AlignTop)
        self.codeline = QLabel()
        self.codeline.setAlignment(Qt.AlignTop)
        self.codeline.setContentsMargins(0, 0, 0, 0)
        self.codeline.move(20, 30)
        self.code = self.codetocode(code)
        vlayout.setContentsMargins(5, 5, 5, 5)
        vlayout.addWidget(self.character)
        vlayout.addWidget(self.codeline)
        vlayout.setAlignment(self.character, Qt.AlignCenter)
        vlayout.setAlignment(self.codeline, Qt.AlignCenter)
        self.setLayout(vlayout)
        self.setContentsMargins(0, 0, 0, 0)
     #   self.show()
        self.disabledchars = 0
        self.is_enabled = True
        self.character.setText(item['_action'].getlabel())
        self.toggled = False
        self.updateView()

    def item_label(self):
        action = self.item.get('_action')
        return action.getlabel() if action is not None else ""

    def codetocode(self, code):
        toReturn = code.replace('1', '.')
        toReturn = toReturn.replace('2', '-')
        return toReturn;

    def enable(self):
        self.is_enabled = True
        self.updateView()

    def disable(self):
        self.is_enabled = False
        self.updateView()

    def updateView (self):
        enabled = self.is_enabled
        codeselectrange = self.disabledchars if enabled  and self.disabledchars > 0 else 0
        self.character.setDisabled(not enabled)
        self.codeline.setDisabled(not enabled)
        charfontsize = int(3.0 * self.config['fontsizescale'] / 100)
        codefontsize = int(5.0 * self.config['fontsizescale'] / 100)
        toggled = self.toggled
        colors = THEME_COLORS
        label = self.item_label().upper() if self.config['upperchars'] else self.item_label()
        self.character.setText("<font style='background-color:{bgcolor};color:{color};font-weight:bold;' size='{fontsize}'>{text}</font>"
                               .format(color=colors['highlight_text'] if toggled else colors['accent'] if enabled else colors['muted'],
                                       text=escape(label),
                                       fontsize=charfontsize, bgcolor=colors['highlight'] if toggled else "transparent"))
        self.codeline.setText("<font size='{fontsize}'><font color='{selected}'>{selecttext}</font><font color='{color}'>{text}</font></font>"
                              .format(text=self.code[codeselectrange:], selecttext=self.code[:codeselectrange],
                                      selected=colors['success'], color=colors['danger'] if enabled else colors['muted'], fontsize=codefontsize))


    def enabled(self):
        return self.character.isEnabled()

    def reset(self):
        self.enable()
        self.disabledchars = -1
        self.tickDitDah()

    def Dit(self):
        #logging.debug(f"[CodeRepresentation] Attempting Dit. Enabled: {self.is_enabled}, Disabled Chars: {self.disabledchars}, Code Length: {len(self.code)}")
        if (self.enabled()):
            if ((self.disabledchars < len(self.code)) and self.code[self.disabledchars] == '.'):
                self.tickDitDah()
                #logging.debug("[CodeRepresentation] Dit successful.")
            else:
                self.disable()
                #logging.debug("[CodeRepresentation] Dit failed - disabling.")

    def Dah(self):
        #logging.debug(f"[CodeRepresentation] Attempting Dah. Enabled: {self.is_enabled}, Disabled Chars: {self.disabledchars}, Code Length: {len(self.code)}")
        if (self.enabled()):
            if ((self.disabledchars < len(self.code)) and self.code[self.disabledchars] == '-'):
                self.tickDitDah()
                #logging.debug("[CodeRepresentation] Dah successful.")
            else:
                self.disable()
                #logging.debug("[CodeRepresentation] Dah failed - disabling.")

    def tickDitDah(self):
        self.disabledchars += 1
        if (self.disabledchars > len(self.code)):
            self.is_enabled = False
        self.updateView()


class ColorIndicatorWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.set_color("green")

    def set_color(self, color):
        status_color = THEME_COLORS['success'] if color == "green" else THEME_COLORS['danger']
        self.setStyleSheet(f"QLabel {{ background-color: {status_color}; border-radius: 8px; }}")


class CodesLayoutViewWidget(QWidget):
    feedbackSignal = pyqtSignal()
    changeLayoutSignal = pyqtSignal(str)
    settingsRequested = pyqtSignal()

    def __init__(self, layout, config, parent=None):
        super().__init__(parent)
        self.layout = layout
        self.config = config
        self.status_bar = QStatusBar()
        self.sound_indicator = ColorIndicatorWidget(self.status_bar)
        self.status_bar.addPermanentWidget(self.sound_indicator)
        self.setupLayout(layout)
        self.setWindowTitle("摩斯码表")
        self.setWindowIcon(QIcon(':/morse-writer.ico'))
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        available = QApplication.desktop().availableGeometry()
        chart_size = self.chart_widget.sizeHint()
        self.resize(min(max(chart_size.width() + 45, 480), available.width() - 40),
                    min(chart_size.height() + 120, available.height() - 80))
        self.adjustPosition()
        self.escapeMorseModeListener = KeyCombinationListener()

    def setAvailableLayouts(self, layouts, active):
        names = {'desktop': '键盘与鼠标', 'main': '主键盘（完整）', 'typing': '字母与候选', 'mouse': '鼠标', 'number': '数字（短码）'}
        self.layout_selector.blockSignals(True)
        self.layout_selector.clear()
        for key in layouts:
            self.layout_selector.addItem(names.get(key, key), key)
        self.layout_selector.setCurrentIndex(self.layout_selector.findData(active))
        self.layout_selector.blockSignals(False)

    def setOutputState(self, held_modifiers, locked):
        held = set(held_modifiers)
        sound = self.config.get('withsound', False)
        self.sound_indicator.set_color('green' if sound else 'red')
        parts = ['已暂停' if self.config.get('off', False) else '输入中',
                 '提示音已开启' if sound else '提示音已关闭']
        if locked:
            parts.append('修饰键锁定已开启')
        if held:
            parts.append('已按住：' + ' + '.join(sorted(held)))
        self.status_bar.showMessage(' · '.join(parts))
        for item in self.crs.values():
            action = item.item['_action']
            item.toggled = ((isinstance(action, ActionKeyStroke) and action.toggle_action and action.key in held)
                            or (isinstance(action, RepeatOnAction) and locked))
            item.updateView()

    def changeLayout(self, layout_name):
        self.changeLayoutSignal.emit(layout_name)


    def adjustPosition(self):
        #logging.debug("Current config: %s", self.config)
        ssize = QApplication.desktop().screenGeometry()
        size = self.frameSize()
        # Explicit conversion to int to ensure no float values slip through
        x = int(self.config['winposx'])
        y = int(self.config['winposy'])

        if self.config['winxaxis'] == 'left':
            x_position = x
        else:
            x_position = ssize.width() - size.width() - x

        if self.config['winyaxis'] == 'top':
            y_position = y
        else:
            y_position = ssize.height() - size.height() - y

        self.move(x_position, y_position)

    def setupLayout(self, layout):
        self.vlayout = QVBoxLayout(self)
        navigation = QHBoxLayout()
        navigation.addWidget(QLabel('当前码表：'))
        self.layout_selector = QComboBox()
        self.layout_selector.setToolTip('切换页面查看对应键位；各页面使用各自的摩斯编码。')
        self.layout_selector.activated.connect(
            lambda index: self.changeLayoutSignal.emit(self.layout_selector.itemData(index)))
        navigation.addWidget(self.layout_selector, 1)
        settings_button = QPushButton('返回设置')
        settings_button.clicked.connect(self.settingsRequested.emit)
        navigation.addWidget(settings_button)
        self.vlayout.addLayout(navigation)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.chart_widget = QWidget()
        chart_layout = QVBoxLayout(self.chart_widget)
        hlayout = QHBoxLayout()
        hlayout.setContentsMargins(0, 0, 0, 0)
        chart_layout.addLayout(hlayout)
        self.keystroke_crs_map = {}
        self.crs = {}
        perrow = layout['column_len']
        for index, item in enumerate(layout['items']):
            if not item.get('emptyspace', False):
                coderep = CodeRepresentation(None, item['code'], item, 'Green', self.config)
                if isinstance(item['_action'], ActionKeyStroke):
                    self.keystroke_crs_map[item['_action'].name] = coderep
                self.crs[item['code']] = coderep
                hlayout.addWidget(coderep)
            if (index + 1) % perrow == 0:
                hlayout = QHBoxLayout()
                hlayout.setContentsMargins(0, 0, 0, 0)
                chart_layout.addLayout(hlayout)
        self.scroll_area.setWidget(self.chart_widget)
        self.vlayout.addWidget(self.scroll_area)
        self.vlayout.addWidget(self.status_bar)


    def Dit(self):
        for item in self.crs.values():
            item.Dit()

    def Dah(self):
        for item in self.crs.values():
            item.Dah()

    def reset(self):
        for item in self.crs.values():
            item.reset()

    def closeEvent(self, event):
        event.ignore()
        self.showMinimized()

    def keyPressEvent(self, event):
        if self.escapeMorseModeListener.keyPressEvent(event):
            self.settingsRequested.emit()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        self.escapeMorseModeListener.keyReleaseEvent(event)

    def updateSoundSupport(self):
        return True

def get_keystroke_state(name):
    state = {
        "down": keyboard.is_pressed(name)
    }
    # Special case handling for CAPS LOCK which needs to check toggle state
    if name.lower() == "capslock":
        state["locked"] = keyboard.is_pressed('caps lock')
    return state


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
    user_data_dir = get_user_data_dir()
    os.makedirs(user_data_dir, exist_ok=True)
    app = CustomApplication(sys.argv)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "摩斯输入", "未检测到系统托盘，无法启动程序。")
        sys.exit(1)

    QApplication.setQuitOnLastWindowClosed(False)

    # Initialize managers
    configmanager = ConfigManager(os.path.join(user_data_dir, "config.json"), default_config=DEFAULT_CONFIG)
    layoutmanager = LayoutManager(os.path.join(user_data_dir, "layouts.json"))

    # Create main window
    window = Window(layoutManager=layoutmanager, configManager=configmanager)
    app.aboutToQuit.connect(window.stopIt)

    # Now that we have the window, initialize actions that may require window reference
    actions = configmanager.initActions(window)
    layoutmanager.set_actions(actions)

    # Finish initializing the window if needed (after actions are available)
    window.postInit()

    # Show or hide the window based on the configuration
    if configmanager.config.get("autostart", False):
        window.hide()
        window.start()
    else:
        window.show()

    # Start the application event loop
    sys.exit(app.exec_())
