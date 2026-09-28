# -*- mode: python ; coding: utf-8 -*-
from PySide6.QtCore import QLibraryInfo

# PySide6 官方 hook 会带上 Qt 插件；这里只补运行时真正用到的 Qt 模块，
# 避免把整个 PySide6 全量塞进去。
qt_plugin_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=[('settings.yaml', '.')],
    hiddenimports=[
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 这些是早期 Web 版/实验分支留下的依赖，本工具都不再用
    excludes=['fastapi', 'uvicorn', 'starlette', 'webview', 'clr_loader',
              'pythonnet', 'flet', 'flet_desktop', 'tkinter', 'pytest',
              'numpy', 'matplotlib', 'IPython', 'PySide6.QtQml',
              'PySide6.QtQuick', 'PySide6.QtWebEngineCore', 'PySide6.Qt3DCore',
              'PySide6.QtMultimedia', 'PySide6.QtNetwork', 'PySide6.QtSql',
              'PySide6.QtTest', 'PySide6.QtCharts', 'PySide6.QtDataVisualization'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DevCleaner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # 有真正的窗口了，不用再开黑控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
