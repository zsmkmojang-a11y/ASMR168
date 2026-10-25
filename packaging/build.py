"""Reproducible local Windows installer build; no system-wide tools required."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'packaging' / 'tools' / 'nsis-3.11'
DIST = ROOT / 'dist' / 'ASMR168'
VERSION = '1.1.1'


def main():
    if not sys.platform.startswith('win'):
        raise RuntimeError('Windows 安装包必须在 Windows 构建')
    if not (TOOLS / 'Bin' / 'makensis.exe').is_file():
        raise RuntimeError('缺少便携 NSIS：packaging/tools/nsis-3.11/Bin/makensis.exe')
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
           '--name', 'ASMR168', '--icon', str(ROOT/'static'/'app.ico'),
           '--distpath', str(ROOT/'dist'), '--workpath', str(ROOT/'build'),
           '--specpath', str(ROOT/'build'), '--paths', str(ROOT),
           '--add-data', str(ROOT/'static') + ';static',
           '--collect-all', 'faster_whisper', '--collect-all', 'ctranslate2',
           '--collect-all', 'onnxruntime', '--collect-all', 'tokenizers',
           '--collect-all', 'yt_dlp', str(ROOT/'launcher.py')]
    subprocess.run(cmd, cwd=ROOT, check=True)
    data = DIST / '_internal'
    if (data / 'models' / 'small' / 'model.bin').exists() or (data / 'bin' / 'ffmpeg.exe').exists():
        raise RuntimeError('安装目录意外包含模型或 FFmpeg')
    notices = DIST / 'THIRD_PARTY.txt'
    notices.write_text('Python component licenses are included with their packages.\n'
                       'FFmpeg and speech models are downloaded separately on request.\n', encoding='utf-8')
    for name in ('README.md',):
        shutil.copy2(ROOT/name, DIST/name)
    (ROOT/'release').mkdir(exist_ok=True)
    subprocess.run([str(TOOLS/'Bin'/'makensis.exe'), '/V2', 'installer.nsi'], cwd=ROOT/'packaging', check=True)
    installer = ROOT/'release'/f'ASMR168-Setup-{VERSION}.exe'
    sha = hashlib.sha256(installer.read_bytes()).hexdigest()
    (ROOT/'release'/f'ASMR168-Setup-{VERSION}.sha256').write_text(f'{sha}  {installer.name}\n', encoding='ascii')
    print(f'INSTALLER={installer}\nSIZE={installer.stat().st_size}\nSHA256={sha}', flush=True)


if __name__ == '__main__':
    main()
