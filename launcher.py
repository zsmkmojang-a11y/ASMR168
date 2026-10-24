"""Windows desktop entry point for the locally hosted WebUI."""
from pathlib import Path
import json
import os
import sys
import threading
import webbrowser


APP_HOME = Path(os.getenv('ASMR_HOME') or (Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'ASMR168'))


def load_env():
    APP_HOME.mkdir(parents=True, exist_ok=True)
    settings = APP_HOME / 'app.env'
    if not settings.exists():
        settings.write_text('# 一伯六十八的ASMR听译间：翻译服务设置（保存后重启应用）\n'
                            '# ASMR_API_KEY=在这里填写密钥\n'
                            '# ASMR_API_BASE=https://你的服务地址/v1\n'
                            '# ASMR_TRANSLATION_MODEL=模型名称\n', encoding='utf-8')
    for line in settings.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key in ('ASMR_API_KEY', 'ASMR_API_BASE', 'ASMR_TRANSLATION_MODEL'):
            os.environ.setdefault(key, value.strip())


def metadata_worker(url, output):
    from yt_dlp import YoutubeDL
    with YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True,
                    'noplaylist': True, 'socket_timeout': 20, 'retries': 1}) as downloader:
        info = downloader.extract_info(url, download=False)
        Path(output).write_text(json.dumps(downloader.sanitize_info(info), ensure_ascii=False), encoding='utf-8')


def self_test():
    import pipeline as p
    import faster_whisper
    import yt_dlp
    env = p.environment()
    assert env['whisper'] and env['yt_dlp']
    assert (p.ROOT / 'static' / 'index.html').is_file()
    return {'ok': True, 'environment': env}


def run():
    if len(sys.argv) >= 4 and sys.argv[1] == '--metadata-worker':
        metadata_worker(sys.argv[2], sys.argv[3])
        return
    load_env()
    if len(sys.argv) > 1 and sys.argv[1] == '--self-test':
        result = self_test()
        if len(sys.argv) > 2:
            Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return
    import pipeline as p
    from server import Handler, ThreadingHTTPServer
    p.DATA.mkdir(parents=True, exist_ok=True)
    last_error = None
    for port in range(8765, 8785):
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
            break
        except OSError as exc:
            last_error = exc
    else:
        raise RuntimeError('本地端口 8765–8784 均被占用') from last_error
    url = f'http://127.0.0.1:{port}'
    threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        if getattr(sys, 'frozen', False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(exc), '一伯六十八的ASMR听译间启动失败', 0x10)
        else:
            raise
        sys.exit(1)
