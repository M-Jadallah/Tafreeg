import { useState } from 'react';
import { Download, Search, Trash2 } from 'lucide-react';
import { del } from '../api';
import { useFetch } from '../hooks/useFetch';
import type { Log } from '../types';

type Response = { items: Log[]; total: number; page: number; page_size: number };
type SettingsResponse = { values: Record<string, unknown> };

export default function Logs() {
  const [level, setLevel] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const { data: settings } = useFetch<SettingsResponse>('/settings');
  const pageSize = Math.max(10, Math.min(100, Number(settings?.values.page_size ?? 25)));
  const path = `/logs?page=${page}&page_size=${pageSize}${level ? `&level=${level}` : ''}${query ? `&search=${encodeURIComponent(query)}` : ''}`;
  const { data, error, reload } = useFetch<Response>(path, 5000);

  async function clear() {
    if (confirm('حذف جميع السجلات؟')) {
      await del('/logs');
      setPage(1);
      reload();
    }
  }

  return (
    <>
      <div className="page-title"><div><h1>السجلات</h1><p>تفاصيل الأخطاء والأحداث التشغيلية</p></div><div className="actions"><a className="button" href="/api/logs/export"><Download size={16}/>تنزيل CSV</a><button className="danger" onClick={clear}><Trash2 size={16}/>مسح السجلات</button></div></div>
      <div className="filters"><div className="search"><Search size={17}/><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="بحث في الرسائل أو رمز الخطأ"/></div><select value={level} onChange={(event) => { setLevel(event.target.value); setPage(1); }}><option value="">كل المستويات</option><option value="critical">حرجة</option><option value="error">أخطاء</option><option value="warning">تحذيرات</option><option value="info">معلومات</option></select></div>
      {error && <div className="alert error">{error}</div>}
      <section className="panel table-panel"><div className="table-wrap"><table className="logs-table"><thead><tr><th>الوقت</th><th>المستوى</th><th>الخدمة</th><th>العامل</th><th>المرحلة</th><th>الرمز</th><th>الرسالة</th></tr></thead><tbody>{data?.items.map((log) => <tr key={log.id} className={`log-${log.level}`}><td>{new Date(log.created_at).toLocaleString('ar-JO')}</td><td><span className={`level ${log.level}`}>{log.level}</span></td><td>{log.service}</td><td>{log.worker_name || '—'}</td><td>{log.stage || '—'}</td><td>{log.error_code || '—'}</td><td><details><summary>{log.message}</summary>{log.technical_details && <pre className="technical">{log.technical_details}</pre>}<small>Trace: {log.trace_id}</small></details></td></tr>)}</tbody></table></div><div className="pagination"><span>{data?.total || 0} سجل</span><div><button disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>السابق</button><b>{page}</b><button disabled={!data || page * pageSize >= data.total} onClick={() => setPage((current) => current + 1)}>التالي</button></div></div></section>
    </>
  );
}
