# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('app/static', 'app/static')]
binaries = []
hiddenimports = ['comtypes', 'dotenv', 'mysql.connector']
tmp_ret = collect_all('pywinauto')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('aspose')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('mysql.connector')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['Desktop_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JTViewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,            # test ke baad False kar dena
    #icon='jtviewer.ico',     # apna icon; file Backend folder mein honi chahiye
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='JTViewer',
)