"""Application-wide dark palette and compact widget styling."""

from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette


THEME_COLORS = {
    "background": "#171B22",
    "surface": "#232A35",
    "input": "#1C222B",
    "text": "#E8EDF3",
    "muted": "#A0AABA",
    "accent": "#85BAFF",
    "success": "#7BDCAB",
    "danger": "#FF9696",
    "highlight": "#315982",
    "highlight_text": "#FFFFFF",
    "border": "#465263",
    "disabled": "#818B9B",
}


def apply_dark_theme(app):
    """Apply the default dark theme to an existing QApplication."""
    app.setStyle("Fusion")
    colors = THEME_COLORS
    palette = QPalette()
    roles = {
        QPalette.Window: "background",
        QPalette.WindowText: "text",
        QPalette.Base: "input",
        QPalette.AlternateBase: "surface",
        QPalette.ToolTipBase: "surface",
        QPalette.ToolTipText: "text",
        QPalette.Text: "text",
        QPalette.Button: "surface",
        QPalette.ButtonText: "text",
        QPalette.BrightText: "danger",
        QPalette.Link: "accent",
        QPalette.LinkVisited: "accent",
        QPalette.Highlight: "highlight",
        QPalette.HighlightedText: "highlight_text",
        QPalette.Light: "border",
        QPalette.Midlight: "surface",
        QPalette.Mid: "border",
        QPalette.Dark: "background",
        QPalette.Shadow: "background",
        QPalette.PlaceholderText: "muted",
    }
    for role, name in roles.items():
        palette.setColor(role, QColor(colors[name]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(colors["disabled"]))
    palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor(colors["surface"]))
    palette.setColor(QPalette.Disabled, QPalette.HighlightedText, QColor(colors["muted"]))
    app.setPalette(palette)

    # Keep the system's font size; prefer a family that renders Chinese clearly.
    available = set(QFontDatabase().families())
    for family in (
        "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
        "Noto Sans CJK SC", "WenQuanYi Micro Hei",
    ):
        if family in available:
            font = QFont(app.font())
            font.setFamily(family)
            app.setFont(font)
            break

    app.setStyleSheet("""
        QLabel, QGroupBox, QRadioButton, QCheckBox {
            color: %(text)s;
        }
        QGroupBox {
            border: 1px solid %(border)s;
            border-radius: 4px;
            margin-top: 0.7em;
            padding-top: 0.3em;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 3px;
        }
        QLineEdit, QComboBox {
            background-color: %(input)s;
            color: %(text)s;
            border: 1px solid %(border)s;
            border-radius: 3px;
            padding: 3px 5px;
            selection-background-color: %(highlight)s;
            selection-color: %(highlight_text)s;
        }
        QLineEdit:focus, QComboBox:focus, QPushButton:focus {
            border-color: %(accent)s;
        }
        QComboBox QAbstractItemView {
            background-color: %(surface)s;
            color: %(text)s;
            border: 1px solid %(border)s;
            selection-background-color: %(highlight)s;
            selection-color: %(highlight_text)s;
        }
        QPushButton {
            background-color: %(surface)s;
            color: %(text)s;
            border: 1px solid %(border)s;
            border-radius: 4px;
            padding: 4px 9px;
        }
        QPushButton:hover {
            border-color: %(accent)s;
            background-color: %(highlight)s;
        }
        QPushButton:pressed, QPushButton:checked {
            background-color: %(highlight)s;
        }
        QPushButton:default {
            border-color: %(accent)s;
        }
        QLabel:disabled, QGroupBox:disabled, QRadioButton:disabled,
        QCheckBox:disabled, QLineEdit:disabled, QComboBox:disabled,
        QPushButton:disabled {
            color: %(disabled)s;
        }
        QLineEdit:disabled, QComboBox:disabled, QPushButton:disabled {
            background-color: %(background)s;
            border-color: %(surface)s;
        }
        QMenu {
            background-color: %(surface)s;
            color: %(text)s;
            border: 1px solid %(border)s;
            padding: 3px;
        }
        QMenu::item:selected {
            background-color: %(highlight)s;
            color: %(highlight_text)s;
        }
        QMenu::item:disabled {
            color: %(disabled)s;
        }
        QMenu::separator {
            height: 1px;
            background-color: %(border)s;
            margin: 4px 6px;
        }
        QToolTip {
            background-color: %(surface)s;
            color: %(text)s;
            border: 1px solid %(border)s;
            padding: 4px;
        }
        QStatusBar {
            background-color: %(surface)s;
            color: %(text)s;
        }
        QStatusBar::item {
            border: none;
        }
    """ % colors)
