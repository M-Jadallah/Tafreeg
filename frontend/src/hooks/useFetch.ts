import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';

export function useFetch<T>(path: string, interval = 0) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const requestInFlight = useRef(false);

  const reload = useCallback(async () => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;

    try {
      setData(await api<T>(path));
      setError('');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'خطأ');
    } finally {
      requestInFlight.current = false;
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void reload();

    if (interval <= 0) return;

    // Use ordinary polling only. The previous permanent EventSource connection
    // kept the browser in a continuous loading/reconnecting state.
    const timer = window.setInterval(() => {
      void reload();
    }, Math.max(interval, 5000));

    return () => window.clearInterval(timer);
  }, [reload, interval]);

  return { data, error, loading, reload, setData };
}
