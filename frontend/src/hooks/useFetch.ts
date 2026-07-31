import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';

export function useFetch<T>(path: string, interval = 0) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    try {
      setData(await api<T>(path));
      setError('');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'خطأ');
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    reload();
    if (!interval) return;
    const source = new EventSource('/api/events/stream', { withCredentials: true });
    source.addEventListener('refresh', reload);
    // Polling remains a fallback if a reverse proxy interrupts SSE.
    const fallback = window.setInterval(reload, Math.max(interval * 3, 15000));
    return () => {
      source.removeEventListener('refresh', reload);
      source.close();
      window.clearInterval(fallback);
    };
  }, [reload, interval]);

  return { data, error, loading, reload, setData };
}
