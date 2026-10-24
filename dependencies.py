"""Opt-in downloads for the two large Windows runtime components."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from urllib import request
import zipfile

import pipeline as p

FFMPEG_URL = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
MODEL_URL = 'https://huggingface.co/Systran/faster-whisper-small'
MODEL_REPO = 'Systran/faster-whisper-small'
MODEL_FILES = ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt')
POOL = ThreadPoolExecutor(max_workers=2)
LOCK = threading.Lock()
PROGRESS = {key: {'state': 'idle', 'message': '', 'downloaded': 0, 'total': 0} for key in ('ffmpeg', 'model')}


def ready(kind):
    if kind == 'ffmpeg':
        return all((p.APP_HOME / 'bin' / name).is_file() for name in ('ffmpeg.exe', 'ffprobe.exe')) or bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))
    return (p.APP_HOME / 'models' / 'small' / '.verified').is_file() and all((p.APP_HOME / 'models' / 'small' / name).is_file() for name in MODEL_FILES) or p.environment()['model_ready']


def status():
    with LOCK:
        current = {key: value.copy() for key, value in PROGRESS.items()}
    for kind, url in (('ffmpeg', FFMPEG_URL), ('model', MODEL_URL)):
        current[kind]['ready'] = ready(kind)
        current[kind]['url'] = url
    return current


def _set(kind, **changes):
    with LOCK:
        PROGRESS[kind].update(changes)


def start(kind):
    if kind not in PROGRESS:
        raise ValueError('未知运行组件')
    with LOCK:
        if PROGRESS[kind]['state'] in ('queued', 'downloading'):
            raise ValueError('该组件正在下载')
        PROGRESS[kind] = {'state': 'queued', 'message': '准备下载…', 'downloaded': 0, 'total': 0}
    POOL.submit(_run, kind)


def _run(kind):
    try:
        _set(kind, state='downloading')
        if kind == 'ffmpeg':
            _download_ffmpeg()
        else:
            _download_model()
        _set(kind, state='complete', message='已安装，可以开始处理')
    except Exception as exc:
        _set(kind, state='error', message=str(exc)[:400])


def _download_ffmpeg():
    target = p.APP_HOME / 'bin'
    temporary = p.APP_HOME / 'downloads' / 'ffmpeg-release-essentials.zip.part'
    temporary.parent.mkdir(parents=True, exist_ok=True)
    _set('ffmpeg', message='正在下载 FFmpeg…')
    try:
        with request.urlopen(FFMPEG_URL + '.sha256', timeout=30) as response:
            checksum_text = response.read(4096).decode('ascii', errors='replace')
        match = re.search(r'\b[a-fA-F0-9]{64}\b', checksum_text)
        if not match:
            raise RuntimeError('FFmpeg 官方校验文件格式无效')
        expected = match.group(0).lower()
        digest = hashlib.sha256()
        with request.urlopen(FFMPEG_URL, timeout=60) as response, temporary.open('wb') as output:
            total = int(response.headers.get('Content-Length', '0'))
            if total > 300 * 1024 ** 2:
                raise RuntimeError('FFmpeg 下载文件异常偏大')
            _set('ffmpeg', total=total)
            downloaded = 0
            while chunk := response.read(1024 * 1024):
                downloaded += len(chunk)
                if downloaded > 300 * 1024 ** 2:
                    raise RuntimeError('FFmpeg 下载文件超过大小限制')
                output.write(chunk)
                digest.update(chunk)
                _set('ffmpeg', downloaded=downloaded)
        if digest.hexdigest() != expected:
            raise RuntimeError('FFmpeg 下载校验失败，请重试')
        staging = temporary.parent / 'ffmpeg-staging'
        staging.mkdir(exist_ok=True)
        with zipfile.ZipFile(temporary) as archive:
            for name in ('ffmpeg.exe', 'ffprobe.exe'):
                matches = [item for item in archive.infolist() if item.filename.replace('\\', '/').endswith('/bin/' + name)]
                if len(matches) != 1 or matches[0].file_size > 300 * 1024 ** 2:
                    raise RuntimeError('FFmpeg 压缩包内容不完整或异常')
                with archive.open(matches[0]) as source, (staging / name).open('wb') as output:
                    shutil.copyfileobj(source, output)
        for name in ('ffmpeg.exe', 'ffprobe.exe'):
            subprocess.run([str(staging / name), '-version'], check=True, capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        target.mkdir(parents=True, exist_ok=True)
        for name in ('ffmpeg.exe', 'ffprobe.exe'):
            os.replace(staging / name, target / name)
        os.environ['PATH'] = str(target) + os.pathsep + os.environ.get('PATH', '')
    finally:
        temporary.unlink(missing_ok=True)


def _download_model():
    from huggingface_hub import snapshot_download
    target = p.APP_HOME / 'models' / 'small'
    target.mkdir(parents=True, exist_ok=True)
    marker = target / '.verified'
    marker.unlink(missing_ok=True)
    _set('model', message='正在从 Hugging Face 下载识别模型，约 500 MB…')
    snapshot_download(repo_id=MODEL_REPO, local_dir=target, allow_patterns=list(MODEL_FILES))
    if not all((target / name).is_file() for name in MODEL_FILES):
        raise RuntimeError('识别模型下载不完整，请重试')
    _set('model', message='正在校验识别模型…')
    from faster_whisper import WhisperModel
    WhisperModel(str(target), device='cpu', compute_type='int8')
    marker.write_text('Systran/faster-whisper-small\n', encoding='ascii')
