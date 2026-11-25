# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['start_app.py'],
    pathex=['backend'],
    binaries=[],
    datas=[('frontend', 'frontend'), ('assets/pocket-money.ico', 'assets'), ('assets/pocket-money.png', 'assets')],
    hiddenimports=['main', 'database', 'models', 'schemas', 'crud', 'crypto_service', 'privat_service', 'webview.platforms.edgechromium'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Receipt recognition normally uses OpenRouter. Excluding the duplicate
    # offline OCR runtime keeps the one-file desktop app small and quick to open.
    excludes=['rapidocr_onnxruntime', 'onnxruntime', 'cv2', 'numpy'],
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
    name='PocketMoneySingle',
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
    icon=['assets\\pocket-money.ico'],
)
