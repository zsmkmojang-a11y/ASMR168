import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib import request, error
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline as p
import server


def sample_rows(count=1):
    return [{'id': i+1, 'start': i*3.0, 'end': i*3+2.5, 'source': 'こんにちは。', 'original': 'こんにちは。',
             'translation': '', 'flags': [], 'reviewed': False} for i in range(count)]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.data = patch.object(p, 'DATA', self.root / 'jobs')
        self.data.start()
        self.audio = self.root / 'test.wav'
        with wave.open(str(self.audio), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes(b'\0\0' * 16000)

    def tearDown(self):
        self.data.stop()
        self.temp.cleanup()

    def make_job(self):
        return p.create_job({'source': str(self.audio), 'description': '测试简介'})

    def test_timecode_rounding(self):
        self.assertEqual(p.timecode(59.9996), '00:01:00,000')
        self.assertEqual(p.timecode(3600.001), '01:00:00,001')

    def test_atomic_write_retries_windows_reader_lock(self):
        target = self.root/'atomic.json'
        replace = Path.replace
        attempts = []
        def temporarily_locked(path, destination):
            attempts.append(1)
            if len(attempts) == 1:
                raise PermissionError('reader holds file')
            return replace(path, destination)
        with patch.object(Path, 'replace', temporarily_locked):
            p.write_json(target, {'saved': True})
        self.assertEqual(p.read_json(target), {'saved': True})
        self.assertEqual(len(attempts), 2)

    def test_validation_overlap_nan_empty(self):
        for value in (float('nan'), -1, 5):
            rows = sample_rows(); rows[0]['start'] = value
            with self.assertRaises(ValueError): p.validate_rows(rows)
        rows = sample_rows(2); rows[1]['start'] = 1
        with self.assertRaises(ValueError): p.validate_rows(rows)
        rows = sample_rows(); rows[0]['source'] = ''
        with self.assertRaises(ValueError): p.validate_rows(rows)
        self.assertEqual(p.validate_rows([]), [])

    def test_split_preserves_words_and_timing(self):
        words = [{'start': i, 'end': i+.8, 'word': w} for i,w in enumerate(['こん','にちは。','今日は','いい','天気。'])]
        result = p.split_segments([{'start': 0, 'end': 4.8, 'text': ''.join(w['word'] for w in words), 'words': words, 'avg_logprob': -1}], 7, 3)
        self.assertEqual(''.join(r['source'] for r in result), 'こんにちは。今日はいい天気。')
        self.assertEqual(result[0]['end'], 1.8)
        self.assertTrue(all(r['flags'] for r in result))
        p.validate_rows(result)

    def test_audio_and_resume_does_not_touch_original(self):
        before = self.audio.read_bytes()
        job = self.make_job()
        result = p.run_job(job['id'], 'audio')
        self.assertEqual(result['done'], ['metadata', 'audio'])
        folder = p.job_path(job['id'])
        stamp = (folder / 'audio.wav').stat().st_mtime_ns
        result = p.run_job(job['id'], 'audio')
        self.assertEqual(stamp, (folder / 'audio.wav').stat().st_mtime_ns)
        self.assertEqual(before, self.audio.read_bytes())
        self.assertEqual(result['state'], 'idle')
        self.assertFalse((folder / '.running').exists())

    def test_no_audio_stream_fails_cleanly(self):
        job = self.make_job()
        with patch.object(p, 'command', return_value=json.dumps({'streams': [], 'format': {}})):
            result = p.run_job(job['id'], 'audio')
        self.assertEqual(result['state'], 'error')
        self.assertIn('没有音轨', result['error'])
        self.assertNotIn('audio', result['done'])

    def test_metadata_failure_falls_back(self):
        config = self.make_job()['config']; config['url'] = 'https://example.invalid/video'
        with patch.object(p, 'command', side_effect=RuntimeError('network error')):
            meta = p.metadata(config)
        self.assertEqual(meta['description'], '测试简介')
        self.assertIn('失败', meta['warning'])

    def test_changed_source_and_lock(self):
        job = self.make_job(); self.audio.write_bytes(b'changed')
        self.assertEqual(p.run_job(job['id'])['state'], 'error')
        folder = p.job_path(job['id']); (folder / '.running').touch()
        with self.assertRaises(ValueError): p.run_job(job['id'])

    def test_translation_partial_resume(self):
        job = self.make_job(); folder = p.job_path(job['id'])
        job['config']['translation_backend'] = 'api'
        p.write_json(folder / 'segments.json', sample_rows(21))
        p.write_json(folder / 'metadata.json', {'description': '测试'})
        calls = []
        def translator(config, context, rows):
            calls.append(len(rows))
            if len(calls) == 2: raise RuntimeError('interrupted')
            return {r['id']: {'source': r['source'], 'translation': '你好。', 'note': ''} for r in rows}
        with patch.object(p, 'translate_batch', side_effect=translator):
            with self.assertRaises(RuntimeError): p.translate(job['config'], folder, lambda x: None)
        self.assertEqual(sum(bool(r['translation']) for r in p.read_json(folder/'segments.json')), 20)
        with patch.object(p, 'translate_batch', side_effect=translator):
            p.translate(job['config'], folder, lambda x: None)
        self.assertEqual(calls, [20,1,1])

    def test_codex_translation_uses_read_only_cli_and_validates_output(self):
        rows = sample_rows(2)
        def fake_run(command, **kwargs):
            self.assertIn('--sandbox', command)
            self.assertEqual(command[command.index('--sandbox') + 1], 'read-only')
            self.assertIn('--ephemeral', command)
            self.assertIn('こんにちは。'.encode('utf-8'), kwargs['input'])
            output = Path(command[command.index('-o') + 1])
            output.write_text(json.dumps({'segments': [
                {'id': row['id'], 'source': row['source'], 'translation': '你好。', 'note': ''}
                for row in rows]}, ensure_ascii=False), encoding='utf-8')
            return type('Result', (), {'returncode': 0})()
        with patch.object(p, 'codex_executable', return_value='codex'), patch.object(p.subprocess, 'run', side_effect=fake_run):
            result = p.translate_batch({}, '简介', rows)
        self.assertEqual(result[1]['translation'], '你好。')
        with patch.object(p, 'codex_executable', return_value=None):
            with self.assertRaisesRegex(ValueError, 'Codex CLI'):
                p.translate_batch({}, '', rows)

    def test_codex_retries_empty_translation_without_saving_it(self):
        rows = sample_rows()
        attempts = []
        def fake_run(command, **kwargs):
            attempts.append(1)
            output = Path(command[command.index('-o') + 1])
            output.write_text(json.dumps({'segments': [{
                'id': 1, 'source': rows[0]['source'],
                'translation': '' if len(attempts) == 1 else '你好。', 'note': ''
            }]}, ensure_ascii=False), encoding='utf-8')
            return type('Result', (), {'returncode': 0})()
        with patch.object(p, 'codex_executable', return_value='codex'), patch.object(p.subprocess, 'run', side_effect=fake_run):
            result = p.translate_batch({}, '', rows)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(result[1]['translation'], '你好。')

    def test_translation_backend_defaults_for_existing_api_settings(self):
        with patch.dict(os.environ, {'ASMR_TRANSLATION_MODEL': 'configured-model'}):
            job = self.make_job()
        self.assertEqual(job['config']['translation_backend'], 'api')
        with patch.dict(os.environ, {'ASMR_TRANSLATION_MODEL': ''}):
            other = self.make_job()
        self.assertEqual(other['config']['translation_backend'], 'codex')

    def test_restart_invalidates_old_exports_even_on_failure(self):
        job = self.make_job(); folder = p.job_path(job['id'])
        job['done'] = list(p.STAGES)
        p.write_json(folder/'job.json', job)
        p.write_json(folder/'segments.json', sample_rows())
        p.write_json(folder/'metadata.json', {})
        p.export_subtitles(folder, job['config'])
        self.assertTrue((folder/'bilingual.srt').exists())
        with patch.object(p, 'translate_batch', side_effect=RuntimeError('offline')):
            result = p.run_job(job['id'], restart='translate')
        self.assertEqual(result['state'], 'error')
        self.assertFalse((folder/'bilingual.srt').exists())
        self.assertFalse((folder/'review.json').exists())

    def test_real_http_translation_contract_and_export(self):
        class MockAPI(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                segments = json.loads(body['messages'][1]['content'])['segments']
                for item in segments: item.update(translation='你好。', note='')
                out = json.dumps({'choices': [{'message': {'content': json.dumps({'segments': segments})}}]}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(out)
        http = ThreadingHTTPServer(('127.0.0.1',0), MockAPI)
        thread = threading.Thread(target=http.serve_forever,daemon=True); thread.start()
        try:
            config = {'api_base':f'http://127.0.0.1:{http.server_port}/v1','translation_model':'test'}
            result = p.translate_batch(config,'',sample_rows())
            self.assertEqual(result[1]['translation'],'你好。')
            job = self.make_job(); folder = p.job_path(job['id']); rows = sample_rows()
            rows[0]['translation'] = result[1]['translation']
            p.write_json(folder/'segments.json',rows)
            review = p.export_subtitles(folder,job['config'])
            text = (folder/'bilingual.srt').read_text(encoding='utf-8-sig')
            self.assertIn('こんにちは。\n你好。',text)
            self.assertIn('尚未人工听音确认',review[0]['flags'])
        finally:
            http.shutdown(); http.server_close(); thread.join()

    def test_server_guards_save_and_media_range(self):
        http = ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread = threading.Thread(target=http.serve_forever,daemon=True); thread.start()
        base = f'http://127.0.0.1:{http.server_port}'
        def post(path, body, **headers):
            req = request.Request(base+path, data=json.dumps(body).encode(), headers={'Content-Type':'application/json','X-ASMR-Client':'webui',**headers})
            return request.urlopen(req)
        try:
            with self.assertRaises(error.HTTPError) as err:
                post('/api/jobs',{},Origin='https://evil.invalid')
            self.assertEqual(err.exception.code,403)
            with post('/api/jobs',{'source':str(self.audio)}) as response: job = json.load(response)
            p.run_job(job['id'],'audio')
            folder = p.job_path(job['id'])
            saved_job = p.read_json(folder/'job.json')
            saved_job['done'] = list(p.STAGES)
            saved_job['state'] = 'complete'
            p.write_json(folder/'job.json', saved_job)
            with post(f"/api/jobs/{job['id']}/save",{'segments':sample_rows()}) as response: self.assertTrue(json.load(response)['ok'])
            self.assertNotIn('translate', p.read_json(folder/'job.json')['done'])
            req = request.Request(base+f"/files/{job['id']}/audio.wav",headers={'Range':'bytes=0-43'})
            with request.urlopen(req) as response:
                self.assertEqual(response.status,206); self.assertEqual(len(response.read()),44)
            with self.assertRaises(error.HTTPError):
                request.urlopen(base+'/files/../../server.py')
        finally:
            http.shutdown(); http.server_close(); thread.join()

    def test_disconnected_client_does_not_receive_error_response(self):
        handler = object.__new__(server.Handler)
        handler.path = '/'
        for disconnect in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            with self.subTest(disconnect=disconnect.__name__), \
                 patch.object(server.Handler, 'allowed', return_value=True), \
                 patch.object(server.Handler, 'send_file', side_effect=disconnect()), \
                 patch.object(server.Handler, 'send_json') as send_json:
                handler.do_GET()
                send_json.assert_not_called()
        handler.path = '/api/jobs'
        handler.headers = {'X-ASMR-Client': 'webui'}
        for disconnect in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            with self.subTest(method='POST', disconnect=disconnect.__name__), \
                 patch.object(server.Handler, 'allowed', return_value=True), \
                 patch.object(server.Handler, 'body', side_effect=disconnect()), \
                 patch.object(server.Handler, 'send_json') as send_json:
                handler.do_POST()
                send_json.assert_not_called()

    def test_onboarding_persists_per_user_home(self):
        with patch.object(p, 'APP_HOME', self.root):
            http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{http.server_port}'
            try:
                with request.urlopen(base+'/api/onboarding') as response:
                    self.assertFalse(json.load(response)['completed'])
                req = request.Request(base+'/api/onboarding', method='POST', data=b'{}',
                                      headers={'Content-Type':'application/json','X-ASMR-Client':'webui'})
                with request.urlopen(req) as response:
                    self.assertTrue(json.load(response)['ok'])
                self.assertTrue(p.read_json(self.root/'onboarding.json')['completed'])
                with request.urlopen(base+'/api/onboarding') as response:
                    self.assertTrue(json.load(response)['completed'])
            finally:
                http.shutdown(); http.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
