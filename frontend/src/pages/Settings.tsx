import { ChangeEvent, useEffect, useState } from 'react';
import { Upload } from 'lucide-react';
import { api, post, put } from '../api';
import { useFetch } from '../hooks/useFetch';

type SettingsResponse = {
  values: Record<string, unknown>;
  fixed: { audio_retention_hours: number; worker_count: number };
  secrets: { deepgram_keys_configured: number; cookies_configured: boolean };
};

type CookieResponse = {
  exists: boolean;
  size?: number;
  modified_at?: string;
  valid_format: boolean;
  line_count?: number;
  expired_count?: number;
  session_count?: number;
  last_test?: Record<string, unknown>;
};

const retryFields: Array<[string, string]> = [
  ['metadata_max_retries', 'محاولات جلب المعلومات'],
  ['download_max_retries', 'محاولات تنزيل الصوت'],
  ['transcode_max_retries', 'محاولات تحويل الصوت'],
  ['deepgram_max_retries', 'محاولات Deepgram'],
  ['export_max_retries', 'محاولات إنشاء الملفات'],
  ['retry_initial_seconds', 'الانتظار الأولي بالثواني'],
  ['retry_multiplier', 'معامل زيادة الانتظار'],
  ['retry_max_seconds', 'أقصى انتظار بالثواني'],
  ['retry_jitter_seconds', 'الفارق العشوائي بالثواني'],
];

const timeoutFields: Array<[string, string]> = [
  ['metadata_timeout_seconds', 'مهلة جلب معلومات الفيديو'],
  ['download_timeout_seconds', 'مهلة تنزيل الصوت'],
  ['ffmpeg_timeout_seconds', 'مهلة FFmpeg'],
  ['deepgram_timeout_seconds', 'مهلة Deepgram'],
];

export default function Settings() {
  const { data, reload } = useFetch<SettingsResponse>('/settings');
  const { data: cookies, reload: reloadCookies } = useFetch<CookieResponse>('/youtube/cookies');
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (data) setValues(data.values);
  }, [data]);

  function change(key: string, value: unknown) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  function numberValue(key: string) {
    return Number(values[key] ?? 0);
  }

  async function save() {
    try {
      await put('/settings', { values });
      setMessage('تم حفظ الإعدادات بنجاح');
      reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'فشل حفظ الإعدادات');
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
      await api('/youtube/cookies', { method: 'POST', body: form });
      setMessage('تم تحديث ملف Cookies');
      reloadCookies();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'فشل رفع Cookies');
    } finally {
      event.target.value = '';
    }
  }

  async function testCookies() {
    try {
      const result = await post<{ success: boolean; error?: string }>('/youtube/cookies/test');
      setMessage(result.success ? 'نجح اختبار Cookies' : `فشل الاختبار: ${result.error ?? 'خطأ غير معروف'}`);
      reloadCookies();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'فشل اختبار Cookies');
    }
  }

  async function retryCookieJobs() {
    try {
      const result = await post<{ message: string }>('/youtube/retry-waiting');
      setMessage(result.message);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'فشل إعادة المهام');
    }
  }

  if (!data) return <div className="center">جارٍ تحميل الإعدادات...</div>;

  return (
    <>
      <div className="page-title">
        <div>
          <h1>الإعدادات</h1>
          <p>التحكم بإعادة المحاولة والمهلات وDeepgram وYouTube والصوت</p>
        </div>
        <button className="primary" onClick={save}>حفظ التغييرات</button>
      </div>

      {message && <div className="alert">{message}</div>}

      <div className="settings-grid">
        <section className="panel">
          <h2>إعادة المحاولة</h2>
          <div className="form-grid compact">
            {retryFields.map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  type="number"
                  step={key === 'retry_multiplier' ? '0.1' : '1'}
                  value={numberValue(key)}
                  onChange={(event) => change(key, Number(event.target.value))}
                />
              </label>
            ))}
          </div>
        </section>

        <section className="panel">
          <h2>المهل الزمنية</h2>
          <div className="form-grid compact">
            {timeoutFields.map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  type="number"
                  value={numberValue(key)}
                  onChange={(event) => change(key, Number(event.target.value))}
                />
              </label>
            ))}
          </div>
          <div className="info-box">جميع القيم في هذا القسم بالثواني.</div>
        </section>

        <section className="panel">
          <h2>Deepgram Whisper</h2>
          <div className="form-grid compact">
            <label>
              النموذج الافتراضي
              <select value={String(values.default_model ?? 'whisper-large')} onChange={(event) => change('default_model', event.target.value)}>
                <option value="whisper-large">Whisper Large</option>
                <option value="whisper-medium">Whisper Medium</option>
                <option value="whisper-small">Whisper Small</option>
                <option value="whisper-base">Whisper Base</option>
                <option value="whisper-tiny">Whisper Tiny</option>
              </select>
            </label>
            <label>
              اللغة الافتراضية
              <input value={String(values.default_language ?? 'ar')} onChange={(event) => change('default_language', event.target.value)} />
            </label>
          </div>
          <div className="check-grid">
            {[
              ['deepgram_punctuate', 'علامات الترقيم'],
              ['deepgram_paragraphs', 'تقسيم الفقرات'],
              ['deepgram_utterances', 'المقاطع الكلامية'],
              ['deepgram_smart_format', 'التنسيق الذكي'],
            ].map(([key, label]) => (
              <label key={key}>
                <input type="checkbox" checked={Boolean(values[key])} onChange={(event) => change(key, event.target.checked)} />
                {label}
              </label>
            ))}
          </div>
          <div className="info-box">مفاتيح Deepgram المضبوطة: <b>{data.secrets.deepgram_keys_configured} من 5</b></div>
        </section>

        <section className="panel">
          <h2>YouTube Cookies</h2>
          <div className="cookie-status">
            <b>{cookies?.exists ? 'ملف Cookies موجود' : 'لا يوجد ملف Cookies'}</b>
            <span>{cookies?.valid_format ? 'صيغة Netscape صحيحة' : 'الصيغة غير مؤكدة'} • {cookies?.line_count ?? 0} Cookie</span>
            {!!cookies?.expired_count && <span className="danger-text">منتهية الصلاحية: {cookies.expired_count}</span>}
            {!!cookies?.session_count && <span>Cookies جلسة: {cookies.session_count}</span>}
            {cookies?.modified_at && <span>آخر تحديث: {new Date(cookies.modified_at).toLocaleString('ar-JO')}</span>}
          </div>
          <div className="actions">
            <label className="button">
              <Upload size={16} /> رفع cookies.txt
              <input type="file" accept=".txt,text/plain" hidden onChange={upload} />
            </label>
            <button onClick={testCookies}>اختبار الملف</button>
            <button onClick={retryCookieJobs}>إعادة مهام Cookies</button>
          </div>
        </section>

        <section className="panel">
          <h2>الصوت والملفات الطويلة</h2>
          <div className="form-grid compact">
            <label>
              معدل الضغط
              <select value={String(values.audio_bitrate ?? '64k')} onChange={(event) => change('audio_bitrate', event.target.value)}>
                <option value="32k">32 kbps</option>
                <option value="48k">48 kbps</option>
                <option value="64k">64 kbps</option>
                <option value="96k">96 kbps</option>
              </select>
            </label>
            <label>
              معدل العينة
              <input type="number" value={numberValue('audio_sample_rate')} onChange={(event) => change('audio_sample_rate', Number(event.target.value))} />
            </label>
            <label>
              عدد القنوات
              <select value={numberValue('audio_channels')} onChange={(event) => change('audio_channels', Number(event.target.value))}>
                <option value={1}>Mono</option>
                <option value={2}>Stereo</option>
              </select>
            </label>
            <label>
              حد اعتبار الملف طويلًا
              <input type="number" value={numberValue('long_audio_threshold_seconds')} onChange={(event) => change('long_audio_threshold_seconds', Number(event.target.value))} />
            </label>
            <label>
              طول الجزء بالثواني
              <input type="number" value={numberValue('chunk_duration_seconds')} onChange={(event) => change('chunk_duration_seconds', Number(event.target.value))} />
            </label>
          </div>
          <div className="info-box">يحذف الصوت المؤقت بعد <b>{data.fixed.audio_retention_hours} ساعة</b>، ولا تحذف التفريغات تلقائيًا.</div>
        </section>

        <section className="panel">
          <h2>النظام ومساحة القرص</h2>
          <div className="form-grid compact">
            <label>
              حجم الصفحة
              <input type="number" value={numberValue('page_size')} onChange={(event) => change('page_size', Number(event.target.value))} />
            </label>
            <label>
              تحذير القرص %
              <input type="number" value={numberValue('disk_warning_percent')} onChange={(event) => change('disk_warning_percent', Number(event.target.value))} />
            </label>
            <label>
              الحد الحرج للقرص %
              <input type="number" value={numberValue('disk_critical_percent')} onChange={(event) => change('disk_critical_percent', Number(event.target.value))} />
            </label>
          </div>
          <div className="info-box">عدد العمال ثابت: <b>{data.fixed.worker_count}</b>. عند بلوغ الحد الحرج يمنع النظام إنشاء مهام جديدة دون حذف أي تفريغ.</div>
        </section>
      </div>
    </>
  );
}
