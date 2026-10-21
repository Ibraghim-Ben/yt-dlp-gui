import os
from PyInstaller.utils.hooks import collect_submodules

datas = [
    ('src/resources/themes', 'src/resources/themes'),
    ('src/resources/translations/*.qm', 'src/resources/translations'),
    ('src/resources/app_icon.ico', 'src/resources'),
    ('src/resources/app_icon.png', 'src/resources'),
]
binaries = []
hiddenimports = [
    'curl_cffi',
    'select',
    'selectors',
    'asyncio',
    'asyncio.windows_events',
    'asyncio.selector_events',
    'websockets',
    'websockets.legacy',
    'websockets.legacy.client',
]
hiddenimports += collect_submodules('yt_dlp')

bin_dir = os.path.join('src', 'resources', 'bin')
for exe in ('ffmpeg.exe', 'ffprobe.exe', 'qjs.exe', 'libwinpthread-1.dll'):
    exe_path = os.path.join(bin_dir, exe)
    if os.path.isfile(exe_path):
        binaries.append((exe_path, 'bin'))


a = Analysis(
    ['run_gui.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt6.QtQuick", "PyQt6.QtQml", "PyQt6.QtPdf",
        "PyQt6.QtDesigner", "PyQt6.Qt3DCore", "PyQt6.Qt3DRender",
        "PyQt6.QtBluetooth", "PyQt6.QtNfc", "PyQt6.QtSql",
        "PyQt6.QtTest", "PyQt6.QtXml", "PyQt6.QtNetwork",
        "PyQt6.QtMultimedia", "PyQt6.QtWebEngine",
    ],
    noarchive=False,
    optimize=2,
)

a.binaries = [
    x for x in a.binaries
    if not any(dll in x[0].lower() for dll in ('opengl32sw.dll', 'd3dcompiler_47.dll'))
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='yt-dlp-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPECPATH, 'src', 'resources', 'app_icon.ico'),
)