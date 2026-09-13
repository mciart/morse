# -*- mode: python ; coding: utf-8 -*-
"""Windows onedir build; only reviewed defaults enter the distribution."""
from pathlib import Path
import sys

project = Path(SPECPATH)
sys.path.insert(0, str(project / 'tools'))
from build_release import pyinstaller_datas, read_version, version_info

app_version = read_version(project / 'version')
a = Analysis(
    [str(project / 'MorseCodeGUI.py')],
    pathex=[str(project)],
    binaries=[],
    datas=pyinstaller_datas(project),
    hiddenimports=['PyQt5.sip', 'keyboard._winkeyboard'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='MorseWriter',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(project / 'res' / 'MorseWriterIcon.ico'),
    version=version_info(app_version),
    uac_admin=False,
    uac_uiaccess=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MorseWriter')
