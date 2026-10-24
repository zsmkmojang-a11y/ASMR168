"""Loopback-only WebUI with same-origin write protection and streamed media."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sys
import threading
import traceback
from urllib.parse import urlparse, unquote
import uuid

import pipeline as p
import dependencies as deps

POOL = ThreadPoolExecutor(max_workers=1)
ACTIVE = set()
MUTEX = threading.Lock()
FILES = {'audio.wav', 'source.srt', 'translation.srt', 'bilingual.srt', 'review.json', 'metadata.json', 'asr.json', 'segments.json'}


def process(job_id, until):
    try:
        p.run_job(job_id, until)
    except Exception:
        traceback.print_exc()
    finally:
        with MUTEX:
            ACTIVE.discard(job_id)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def allowed(self):
        hosts = {f'localhost:{self.server.server_port}', f'127.0.0.1:{self.server.server_port}'}
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        return host in hosts and (not origin or origin in {'http://' + h for h in hosts}) and self.headers.get('Sec-Fetch-Site') != 'cross-site'

    def send_json(self, value, code=200):
        body = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise ValueError('请求须使用 application/json')
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 16 * 1024 * 1024:
            raise ValueError('请求大小无效或超过 16 MB')
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError('请求必须为 JSON 对象')
        return value

    def send_file(self, path, download=False):
        if not path.is_file():
            self.send_json({'error': '文件尚未生成'}, 404)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        partial = self.headers.get('Range')
        if partial:
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', partial)
            if not match:
                self.send_error(416)
                return
            start = int(match[1])
            end = min(int(match[2]) if match[2] else end, end)
            if start > end:
                self.send_error(416)
                return
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(max(0, end - start + 1)))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        if download:
            self.send_header('Content-Disposition', f'attachment; filename="{path.name}"')
        self.end_headers()
        with path.open('rb') as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                block = f.read(min(1024 * 1024, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def do_GET(self):
        if not self.allowed():
            self.send_json({'error': '仅允许本机同源访问'}, 403)
            return
        try:
            path = urlparse(self.path).path
            if path == '/api/environment':
                self.send_json(p.environment())
            elif path == '/api/dependencies':
                self.send_json(deps.status())
            elif path == '/api/onboarding':
                settings = p.APP_HOME / 'onboarding.json'
                self.send_json(p.read_json(settings) if settings.exists() else {'completed': False})
            elif path == '/api/jobs':
                jobs = [p.read_json(f) for f in p.DATA.glob('*/job.json')]
                for job in jobs:
                    job['active'] = job['id'] in ACTIVE
                    if job['state'] in ('running', 'queued') and not job['active']:
                        job['state'] = 'interrupted'
                self.send_json(sorted(jobs, key=lambda j: j['created'], reverse=True))
            elif re.fullmatch('/api/jobs/[a-f0-9]{32}', path):
                folder = p.job_path(path.split('/')[-1])
                job = p.read_json(folder / 'job.json')
                job['active'] = job['id'] in ACTIVE
                for name in ('segments', 'metadata', 'review'):
                    file = folder / (name + '.json')
                    job[name] = p.read_json(file) if file.exists() else ([] if name != 'metadata' else {})
                job['files'] = sorted(name for name in FILES if (folder / name).exists())
                self.send_json(job)
            elif path.startswith('/files/'):
                parts = path.split('/')
                if len(parts) != 4 or parts[3] not in FILES:
                    raise ValueError('无效文件')
                self.send_file(p.job_path(parts[2]) / parts[3], parts[3] != 'audio.wav')
            else:
                files = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css',
                         '/logo.jpg': 'logo.jpg', '/favicon.ico': 'app.ico', '/brand.css': 'brand.css'}
                if path not in files:
                    self.send_json({'error': '页面不存在'}, 404)
                else:
                    self.send_file(p.ROOT / 'static' / files[path])
        except (ValueError, KeyError, OSError) as exc:
            self.send_json({'error': str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if not self.allowed() or self.headers.get('X-ASMR-Client') != 'webui':
            self.send_json({'error': '仅允许本机 WebUI 提交请求'}, 403)
            return
        try:
            path = urlparse(self.path).path
            if path == '/api/upload':
                length = int(self.headers.get('Content-Length', 0))
                suffix = Path(unquote(self.headers.get('X-Filename', ''))).suffix.lower()
                if suffix not in p.MEDIA or not 0 < length <= 50 * 1024 ** 3:
                    raise ValueError('文件格式不支持或文件超过 50 GB')
                folder = p.DATA / 'uploads'
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / (uuid.uuid4().hex + suffix)
                temp = target.with_suffix('.partial')
                try:
                    with temp.open('wb') as f:
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise ValueError('上传中断')
                            f.write(chunk)
                            remaining -= len(chunk)
                    temp.replace(target)
                finally:
                    temp.unlink(missing_ok=True)
                self.send_json({'source': str(target)})
                return
            body = self.body()
            if path in ('/api/dependencies/ffmpeg', '/api/dependencies/model'):
                deps.start(path.rsplit('/', 1)[-1])
                self.send_json({'ok': True})
                return
            if path == '/api/onboarding':
                p.APP_HOME.mkdir(parents=True, exist_ok=True)
                p.write_json(p.APP_HOME / 'onboarding.json', {'completed': True, 'version': 1})
                self.send_json({'ok': True})
                return
            if path == '/api/jobs':
                self.send_json(p.create_job(body), 201)
                return
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{32})/(run|save)', path)
            if not match:
                raise ValueError('接口不存在')
            job_id, action = match.groups()
            folder = p.job_path(job_id)
            with MUTEX:
                if job_id in ACTIVE or (folder / '.running').exists():
                    raise ValueError('任务正在处理或留有中断锁，暂不能修改；参见 README 的中断恢复')
                job = p.read_json(folder / 'job.json')
                if action == 'run':
                    until = body.get('until', 'export')
                    if until not in p.STAGES:
                        raise ValueError('无效阶段')
                    ACTIVE.add(job_id)
                    job.update(state='queued', error='')
                    p.write_json(folder / 'job.json', job)
                    POOL.submit(process, job_id, until)
                    self.send_json({'ok': True})
                else:
                    rows = p.validate_rows(body['segments'])
                    p.write_json(folder / 'segments.json', rows)
                    p.export_subtitles(folder, job['config'])
                    if any(not row['translation'] for row in rows):
                        job['done'] = [s for s in job['done'] if s not in ('translate', 'export')]
                        job.update(state='idle', error='')
                        p.write_json(folder / 'job.json', job)
                    self.send_json({'ok': True, 'count': len(rows)})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.send_json({'error': str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    p.DATA.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    if sys.stdout:
        print(f'一伯六十八的ASMR听译间 http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        POOL.shutdown(wait=True)


if __name__ == '__main__':
    main()
