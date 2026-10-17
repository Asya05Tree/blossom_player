# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui', 'ui'),         # Упаковываем интерфейс index.html
        ('assets', 'assets'), # Упаковываем папки картинок и треков
        ('ffmpeg', 'ffmpeg'), # ffmpeg.exe/ffprobe.exe — нужны yt-dlp/spotdl без системной установки
        ('tools', 'tools'),   # fpcalc.exe (отпечатки для дублей) + deno.exe (JS-испытания YouTube)
    ],
    hiddenimports=[
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebChannel',
        'pygame',
        'mutagen',
        'yt_dlp'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BlossomPlayer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # Отключаем черную консоль, оставляем только красивое окно
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements=None,
    icon=None # Можешь добавить сюда путь к .ico иконке, если захочешь
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BlossomPlayer',
)
