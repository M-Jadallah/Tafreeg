import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, Search, Trash2 } from 'lucide-react';
import { del, downloadPost, formatDuration, post } from '../api';
import StatusBadge from '../components/StatusBadge';
import { useFetch } from '../hooks/useFetch';
import type { Batch, Job } from '../types';
import './Jobs.bulk-download.css';

type Response = { items: Job[]; total: number; page: number; page_size: number };
type SettingsResponse = { values: Record<string, unknown> };
type ExportFormat = 'docx' | 'txt' | 'json';

const exportLabels: Record<ExportFormat, string> = {
  docx: 'Word',
  txt: 'TXT',
  json: 'JSON',
};

export default function Jobs() {
  const [status, setStatus] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string[]>([]);
  const [formats, setFormats] = useState<ExportFormat[]>(['docx']);
  const [downloading, setDownloading] = useState(false);
  const [message, setMessage] = useState('');
  const { data: settings } = useFetch<SettingsResponse>('/settings');
  const { data: batches, reload: reloadBatches } = useFetch<Batch[]>('/batches?limit=50', 10000);
  const pageSize = Math.max(10, Math.min(100, Number(settings?.values.page_size ?? 25)));
  const path = `/jobs?page=${page}&page_size=${pageSize}${status ? `&status=${status}` : ''}${query ? `&search=${encodeURIComponent(query)}` : ''}`;
  const { data, loading, error, reload } = useFetch<Response>(path, 5000);

  useEffect(() => {
    const visible = new Set(data?.items.map((item) => item.id) ?? []);
    setSelected((current) => current.filter((id) => visible.has(id)));
  }, [data]);

  const downloadableSelected = useMemo(
    () =>
      data?.items
        .filter((job) => selected.includes(job.id) && job.status === 'completed')
        .map((job) => job.id) ?? [],
    [data, selected],
  );

  function toggle(id: string) {
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  }

  function togglePage() {
    const ids = data?.items.map((item) => item.id) ?? [];
    const allSelected = ids.length > 0 && ids.every((id) => selected.includes(id));
    setSelected(allSelected ? [] : ids);
  }

  function toggleFormat(format: ExportFormat) {
    setFormats((current) =>
      current.includes(format)
        ? current.filter((item) => item !== format)
        : [...current, format],
    );
  }

  async function downloadSelected() {
    if (!downloadableSelected.length) {
      setMessage('حدد تفريغًا مكتملًا واحدًا على الأقل');
      return;
    }

    if (!formats.length) {
      setMessage('اختر صيغة واحدة على الأقل');
      return;
    }

    try {
      setDownloading(true);
      setMessage('');
      await downloadPost(
        '/jobs/bulk-export',
        { job_ids: downloadableSelected, formats },
        'tafreeg-exports.zip',
      );
      setMessage(
        `تم تجهيز ${downloadableSelected.length} تفريغًا بصيغة ${formats
          .map((format) => exportLabels[format])
          .join('، ')}`,
      );
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'فشل تنزيل التفريغات');
    } finally {
      setDownloading(false);
    }
  }

  async function deleteSelected() {
    if (!selected.length || !confirm(`حذف ${selected.length} تفريغًا وجميع ملفاتها نهائيًا؟`)) return;

    try {
      const result = await post<{ message: string }>('/jobs/bulk-delete', { job_ids: selected });
      setMessage(result.message);
      setSelected([]);
      reload();
      reloadBatches();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'فشل حذف التفريغات');
    }
  }

  async function deleteBatch(batch: Batch) {
    const label = batch.title || batch.source_url;
    if (!confirm(`حذف «${label}» وجميع التفريغات التابعة لها نهائيًا؟`)) return;

    try {
      const result = await del<{ message: string }>(`/batches/${batch.id}`);
      setMessage(result.message);
      setSelected([]);
      reload();
      reloadBatches();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'فشل حذف القائمة');
    }
  }

  return (
    <>
      <div className="page-title">
        <div>
          <h1>التفريغات</h1>
          <p>جميع فيديوهاتك وقوائم التشغيل في مكان واحد</p>
        </div>
        {selected.length > 0 && (
          <button className="danger" onClick={deleteSelected}>
            <Trash2 size={16} />
            حذف المحدد ({selected.length})
          </button>
        )}
      </div>

      {message && <div className="alert">{message}</div>}

      {selected.length > 0 && (
        <section className="panel bulk-export-toolbar">
          <div className="bulk-export-summary">
            <b>تنزيل التفريغات المحددة</b>
            <small>
              {downloadableSelected.length} مكتمل من أصل {selected.length} محدد
            </small>
          </div>

          <div className="bulk-format-options" aria-label="صيغ التنزيل">
            {(Object.keys(exportLabels) as ExportFormat[]).map((format) => (
              <label key={format} className={formats.includes(format) ? 'active' : ''}>
                <input
                  type="checkbox"
                  checked={formats.includes(format)}
                  onChange={() => toggleFormat(format)}
                />
                {exportLabels[format]}
              </label>
            ))}
          </div>

          <button
            className="primary bulk-download-button"
            disabled={downloading || !downloadableSelected.length || !formats.length}
            onClick={downloadSelected}
          >
            <Download size={17} />
            {downloading ? 'جارٍ تجهيز الملف...' : `تنزيل المحدد (${downloadableSelected.length})`}
          </button>
        </section>
      )}

      {!!batches?.length && (
        <details className="panel batches-panel">
          <summary>الروابط وقوائم التشغيل الأخيرة ({batches.length})</summary>
          <div className="batch-list">
            {batches.map((batch) => (
              <div className="batch-row" key={batch.id}>
                <div>
                  <b>{batch.title || (batch.source_type === 'playlist' ? 'قائمة تشغيل' : 'فيديو')}</b>
                  <small>
                    {batch.total_jobs} فيديو • {batch.completed_jobs} مكتمل • {batch.failed_jobs} فاشل
                  </small>
                </div>
                <StatusBadge value={batch.status} />
                <button className="danger compact-button" onClick={() => deleteBatch(batch)}>
                  <Trash2 size={15} />
                  حذف الكل
                </button>
              </div>
            ))}
          </div>
        </details>
      )}

      <div className="filters">
        <div className="search">
          <Search size={17} />
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
            placeholder="بحث بالعنوان أو القناة"
          />
        </div>
        <select
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setPage(1);
          }}
        >
          <option value="">كل الحالات</option>
          <option value="queued">بالانتظار</option>
          <option value="downloading">تنزيل</option>
          <option value="transcribing">تفريغ</option>
          <option value="completed">مكتملة</option>
          <option value="failed">فاشلة</option>
          <option value="waiting_for_cookies">تحتاج Cookies</option>
        </select>
      </div>

      {error && <div className="alert error">{error}</div>}

      <section className="panel table-panel">
        <div className="table-wrap">
          <table className="jobs-table">
            <thead>
              <tr>
                <th className="select-cell">
                  <input
                    type="checkbox"
                    aria-label="تحديد الصفحة"
                    checked={
                      !!data?.items.length &&
                      data.items.every((item) => selected.includes(item.id))
                    }
                    onChange={togglePage}
                  />
                </th>
                <th>الفيديو</th>
                <th>الحالة</th>
                <th>التقدم</th>
                <th>العامل</th>
                <th>المدة</th>
                <th>المحاولات</th>
                <th>التاريخ</th>
                <th className="download-column">التنزيل</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((job) => (
                <tr key={job.id}>
                  <td className="select-cell">
                    <input
                      type="checkbox"
                      aria-label={`تحديد ${job.title || job.id}`}
                      checked={selected.includes(job.id)}
                      onChange={() => toggle(job.id)}
                    />
                  </td>
                  <td>
                    <Link className="job-title" to={`/jobs/${job.id}`}>
                      {job.thumbnail_url && <img src={job.thumbnail_url} alt="" />}
                      <span>
                        <b>{job.title || 'جارٍ قراءة العنوان'}</b>
                        <small>{job.channel || job.youtube_video_id || job.id}</small>
                      </span>
                    </Link>
                  </td>
                  <td><StatusBadge value={job.status} /></td>
                  <td>
                    <div className="mini-progress">
                      <i style={{ width: `${job.progress}%` }} />
                      <span>{Math.round(job.progress)}%</span>
                    </div>
                  </td>
                  <td>{job.worker_name || '—'}</td>
                  <td>{formatDuration(job.duration_seconds)}</td>
                  <td>{job.retry_count}</td>
                  <td>{new Date(job.created_at).toLocaleDateString('ar-JO')}</td>
                  <td className="download-column">
                    {job.status === 'completed' ? (
                      <div className="row-export-actions">
                        {(Object.keys(exportLabels) as ExportFormat[]).map((format) => (
                          <a
                            key={format}
                            className="row-export-link"
                            href={`/api/jobs/${job.id}/export/${format}`}
                            title={`تنزيل ${exportLabels[format]}`}
                          >
                            <Download size={14} />
                            {exportLabels[format]}
                          </a>
                        ))}
                      </div>
                    ) : (
                      <span className="download-unavailable">—</span>
                    )}
                  </td>
                </tr>
              ))}
              {!loading && !data?.items.length && (
                <tr>
                  <td colSpan={9} className="empty">لا توجد نتائج</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="pagination">
          <span>{data?.total || 0} مهمة</span>
          <div>
            <button disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>
              السابق
            </button>
            <b>{page}</b>
            <button
              disabled={!data || page * pageSize >= data.total}
              onClick={() => setPage((current) => current + 1)}
            >
              التالي
            </button>
          </div>
        </div>
      </section>
    </>
  );
}
