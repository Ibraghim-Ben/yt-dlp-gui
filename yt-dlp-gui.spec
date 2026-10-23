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
    'mutagen',
]
hiddenimports += collect_submodules('yt_dlp')

bin_dir = os.path.join('src', 'resources', 'bin')
for exe in ('ffmpeg.exe', 'qjs.exe', 'libwinpthread-1.dll'):
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
        "tkinter", "unittest", "pydoc",
    ],
    noarchive=False,
    optimize=2,
)

BLOCKED_BINARIES = {
    'opengl32sw.dll',
    'd3dcompiler_47.dll',
    'qt6pdf.dll',
    'qpdf.dll',
    'qtiff.dll',
    'qicns.dll',
    'qwbmp.dll',
    'qtga.dll',
    'qminimal.dll',
    'qoffscreen.dll',
    'qtuiotouchplugin.dll',
}

a.binaries = [
    x for x in a.binaries
    if os.path.basename(x[0]).lower() not in BLOCKED_BINARIES
]

a.datas = [
    x for x in a.datas
    if not any(bad in x[0].lower() for bad in ('setuptools', 'dist-info', 'egg-info'))
]

a.pure = [
    x for x in a.pure
    if not any(x[0].startswith(pkg) for pkg in ('setuptools', 'pkg_resources', 'pip', '_distutils_hack', 'distutils'))
]

a.scripts = [
    x for x in a.scripts
    if 'setuptools' not in x[0].lower()
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