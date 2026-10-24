"""Optional real-browser smoke test. Requires playwright + installed Edge."""
from pathlib import Path
import json
import os
import sys
import wave
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'tests' / 'artifacts'
ARTIFACTS.mkdir(exist_ok=True)
sample = ARTIFACTS / 'sample.wav'
if not sample.exists():
    with wave.open(str(sample), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 16000 * 6)
BASE = os.getenv('ASMR_TEST_BASE', 'http://127.0.0.1:8765')

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(BASE)
    page.wait_for_load_state('networkidle')
    expect(page.get_by_role('heading',name='留住低语，译得清楚。')).to_be_visible()
    if os.getenv('ASMR_EXPECT_FIRST_RUN') == '1':
        expect(page.locator('#tutorial')).to_be_visible()
        page.screenshot(path=str(ARTIFACTS/'first-run-tutorial.png'),full_page=True)
    if page.locator('#tutorial').evaluate('(dialog) => dialog.open'):
        for _ in range(3):
            page.locator('#tutorial-next').click()
        expect(page.locator('#tutorial-progress')).to_have_text('4 / 4')
        page.locator('#tutorial-next').click()
        expect(page.locator('#tutorial')).not_to_be_visible()
        page.reload(); page.wait_for_load_state('networkidle')
        expect(page.locator('#tutorial')).not_to_be_visible()
    page.locator('#help').click()
    expect(page.locator('#tutorial')).to_be_visible()
    page.locator('#tutorial-later').click()
    page.screenshot(path=str(ARTIFACTS/'desktop-empty.png'),full_page=True)
    # Create a real audio extraction job through the form.
    page.get_by_label('视频 / 音频原文件').fill(str(sample))
    page.get_by_label('处理到').select_option('audio')
    page.get_by_role('button',name='开始处理').click()
    page.wait_for_function('document.querySelector("audio").getAttribute("src") && !document.querySelector("#continue").disabled', timeout=30000)
    jobs = page.request.get(BASE+'/api/jobs').json()
    job_id = jobs[0]['id']
    # Fixture subtitles for deterministic editing tests; ASR is tested separately.
    rows = [{'id':1,'start':0.1,'end':4.5,'source':'これはテストです。次の文です。','original':'これはテストです。次の文です。','translation':'这是测试。下一句话。','flags':['浏览器测试样例'],'reviewed':False}]
    response = page.request.post(f'{BASE}/api/jobs/{job_id}/save', data={'segments':rows}, headers={'X-ASMR-Client':'webui'})
    assert response.ok, response.text()
    page.locator('.job-item').first.click()
    source = page.get_by_role('textbox',name='第 1 条原文',exact=True)
    translation = page.get_by_role('textbox',name='第 1 条译文',exact=True)
    expect(source).to_have_value(rows[0]['source'])
    translation.fill('这是测试。第二句话。')
    page.get_by_role('checkbox',name='第 1 条已听音确认').check()
    def check_save_locked(route):
        expect(source).to_be_disabled()
        expect(translation).to_be_disabled()
        route.continue_()
    page.route('**/save', check_save_locked)
    page.get_by_role('button',name='保存并导出').click()
    expect(page.locator('#save-state')).to_contain_text('已载入最新字幕')
    page.unroute('**/save', check_save_locked)
    # Split at independently selected bilingual boundaries.
    source.evaluate('(el) => el.setSelectionRange(9,9)')
    translation.evaluate('(el) => el.setSelectionRange(5,5)')
    page.get_by_role('button',name='切分',exact=True).click()
    expect(page.locator('.subtitle-row')).to_have_count(2)
    page.get_by_role('button',name='保存并导出').click()
    expect(page.locator('#save-state')).to_contain_text('已载入最新字幕')
    with page.expect_download() as download:
        page.get_by_role('link',name='双语 SRT',exact=True).click()
    download.value.save_as(str(ARTIFACTS/'browser-export.srt'))
    assert '这是测试。' in (ARTIFACTS/'browser-export.srt').read_text(encoding='utf-8-sig')
    # Invalid timing must not be persisted.
    page.get_by_role('spinbutton',name='第 2 条开始秒数').fill('0')
    page.get_by_role('button',name='保存并导出').click()
    expect(page.locator('#toast')).to_contain_text('重叠')
    page.on('dialog',lambda dialog: dialog.accept())
    page.locator('.job-item').first.click()
    expect(page.get_by_role('spinbutton',name='第 2 条开始秒数')).not_to_have_value('0')
    page.get_by_role('button',name='试听',exact=True).first.click()
    page.wait_for_function('document.querySelector("audio").currentTime > 0.1')
    page.locator('audio').evaluate('(audio) => audio.pause()')
    expect(page.locator('#toast')).to_be_hidden(timeout=10000)
    page.screenshot(path=str(ARTIFACTS/'desktop-editor.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'mobile horizontal overflow'
    page.screenshot(path=str(ARTIFACTS/'mobile-editor.png'),full_page=True)
    assert not errors, errors
    print(json.dumps({'passed':True,'job_id':job_id,'browser_errors':errors,'screenshots':str(ARTIFACTS)}))
    browser.close()
