from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH)
datas = collect_data_files("agent_usage_monitor")
datas += collect_data_files("textual")
datas += copy_metadata("agent-usage-monitor")
hiddenimports = collect_submodules("textual")
hiddenimports += collect_submodules("uvicorn")

analysis = Analysis(
    [str(root / "packaging" / "pyinstaller_entry.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="agent-monitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
