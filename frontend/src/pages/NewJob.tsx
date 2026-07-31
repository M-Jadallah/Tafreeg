import { FormEvent, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { post } from '../api';
import { useFetch } from '../hooks/useFetch';

type SettingsResponse = { values: Record<string, unknown> };

export default function NewJob() {
  const { data: settings } = useFetch<SettingsResponse>('/settings');
  const [url, setUrl] = useState('');
  const [model, setModel] = useState('whisper-large');
  const [language, setLanguage] = useState('ar');
  const [paragraphs, setParagraphs] = useState(true);
  const [utterances, setUtterances] = useState(true);
  const [punctuate, setPunctuate] = useState(true);
  const [smartFormat, setSmartFormat] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    if (!settings) return;
    const values = settings.values;
    setModel(String(values.default_model ?? 'whisper-large'));
    setLanguage(String(values.default_language ?? 'ar'));
    setParagraphs(Boolean(values.deepgram_paragraphs ?? true));
    setUtterances(Boolean(values.deepgram_utterances ?? true));
    setPunctuate(Boolean(values.deepgram_punctuate ?? true));
    setSmartFormat(Boolean(values.deepgram_smart_format ?? true));
  }, [settings]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage('');
    try {
      await post('/batches', {
        url: url.trim(),
        model,
        language,
        paragraphs,
        utterances,
        punctuate,
        smart_format: smartFormat,
      });
      setMessage('تم استلام الرابط وبدأ استخراج الفيديوهات');
      window.setTimeout(() => navigate('/jobs'), 900);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'فشل إنشاء المهمة');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-title">
        <div>
          <h1>تفريغ جديد</h1>
          <p>ألصق رابط فيديو YouTube أو قائمة تشغيل كاملة</p>
        </div>
      </div>
      <form className="panel form" onSubmit={submit}>
        <label className="wide">
          رابط YouTube
          <textarea
            rows={3}
            placeholder="https://www.youtube.com/watch?v=... أو playlist?..."
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            required
          />
        </label>
        <div className="form-grid">
          <label>
            نموذج Whisper
            <select value={model} onChange={(event) => setModel(event.target.value)}>
              <option value="whisper-large">Whisper Large</option>
              <option value="whisper-medium">Whisper Medium</option>
              <option value="whisper-small">Whisper Small</option>
              <option value="whisper-base">Whisper Base</option>
              <option value="whisper-tiny">Whisper Tiny</option>
            </select>
          </label>
          <label>
            اللغة
            <input value={language} onChange={(event) => setLanguage(event.target.value)} placeholder="ar أو auto" />
          </label>
        </div>
        <div className="check-grid">
          <label><input type="checkbox" checked={punctuate} onChange={(event) => setPunctuate(event.target.checked)} />علامات الترقيم</label>
          <label><input type="checkbox" checked={paragraphs} onChange={(event) => setParagraphs(event.target.checked)} />تقسيم الفقرات</label>
          <label><input type="checkbox" checked={utterances} onChange={(event) => setUtterances(event.target.checked)} />المقاطع الكلامية</label>
          <label><input type="checkbox" checked={smartFormat} onChange={(event) => setSmartFormat(event.target.checked)} />التنسيق الذكي</label>
        </div>
        <div className="info-box">
          <b>كيف يعمل؟</b>
          <span>ينشئ النظام مهمة مستقلة لكل فيديو، ويعالج خمسة ملفات في الوقت نفسه. تحفظ النتائج دائمًا، بينما يحذف الصوت المؤقت بعد 24 ساعة.</span>
        </div>
        {message && <div className={`alert ${message.startsWith('تم') ? 'success' : 'error'}`}>{message}</div>}
        <button className="primary" disabled={busy}>{busy ? 'جارٍ الإرسال...' : 'بدء التفريغ'}</button>
      </form>
    </>
  );
}
