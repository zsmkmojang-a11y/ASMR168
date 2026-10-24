import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dependencies as deps
import pipeline as p


class FakeResponse(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body))}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.home_patch = patch.object(p, 'APP_HOME', self.home)
        self.home_patch.start()

    def tearDown(self):
        self.home_patch.stop()
        self.temp.cleanup()

    def test_ffmpeg_checksum_failure_leaves_no_binaries(self):
        with patch.object(deps.request, 'urlopen', side_effect=[FakeResponse(b'0' * 64), FakeResponse(b'bad archive')]):
            with self.assertRaisesRegex(RuntimeError, '校验失败'):
                deps._download_ffmpeg()
        self.assertFalse((self.home / 'bin' / 'ffmpeg.exe').exists())

    def test_ffmpeg_verified_zip_installs_only_requested_tools(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('ffmpeg-test/bin/ffmpeg.exe', b'fake ffmpeg')
            archive.writestr('ffmpeg-test/bin/ffprobe.exe', b'fake ffprobe')
            archive.writestr('ffmpeg-test/bin/unrelated.exe', b'unrelated')
        archive_bytes = data.getvalue()
        checksum = hashlib.sha256(archive_bytes).hexdigest().encode()
        with patch.object(deps.request, 'urlopen', side_effect=[FakeResponse(checksum), FakeResponse(archive_bytes)]), patch.object(deps.subprocess, 'run'):
            deps._download_ffmpeg()
        self.assertEqual((self.home / 'bin' / 'ffmpeg.exe').read_bytes(), b'fake ffmpeg')
        self.assertEqual((self.home / 'bin' / 'ffprobe.exe').read_bytes(), b'fake ffprobe')
        self.assertFalse((self.home / 'bin' / 'unrelated.exe').exists())

    def test_model_download_requires_complete_files(self):
        def incomplete(**kwargs):
            (kwargs['local_dir'] / 'model.bin').write_bytes(b'partial')
        with patch('huggingface_hub.snapshot_download', side_effect=incomplete):
            with self.assertRaisesRegex(RuntimeError, '不完整'):
                deps._download_model()
        with patch.object(p, 'model_default', return_value='small'):
            self.assertFalse(deps.ready('model'))

    def test_model_load_failure_does_not_mark_verified(self):
        def complete(**kwargs):
            for name in deps.MODEL_FILES:
                (kwargs['local_dir'] / name).write_bytes(b'broken')
        with patch('huggingface_hub.snapshot_download', side_effect=complete), patch('faster_whisper.WhisperModel', side_effect=RuntimeError('invalid model')):
            with self.assertRaisesRegex(RuntimeError, 'invalid model'):
                deps._download_model()
        self.assertFalse((self.home / 'models' / 'small' / '.verified').exists())


if __name__ == '__main__':
    unittest.main()
