# PyInstaller build for the gun simulator UI.
#   pyinstaller gun_sim.spec      ->  dist/GunSimulator.exe
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["launcher.py"],
    datas=[
        ("gun_sim/ui/static", "gun_sim/ui/static"),
        ("configs", "configs"),
    ],
    # The UI draws its own charts; matplotlib is only used by the CLI --plot flag.
    excludes=["matplotlib", "tkinter", "PIL", "pytest"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="GunSimulator",
    console=False,  # a windowed app: the UI opens in its own native window
    upx=False,
)
