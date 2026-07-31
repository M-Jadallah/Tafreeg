import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { api } from '../api';
import Layout from './Layout';

type AuthState = 'checking' | 'authenticated' | 'unauthenticated';

export default function ProtectedLayout() {
  const [state, setState] = useState<AuthState>('checking');

  useEffect(() => {
    let active = true;

    const markUnauthenticated = () => {
      if (active) setState('unauthenticated');
    };

    window.addEventListener('auth:unauthorized', markUnauthenticated);

    api<{ authenticated: boolean }>('/auth/me')
      .then(() => {
        if (active) setState('authenticated');
      })
      .catch(() => {
        if (active) setState('unauthenticated');
      });

    return () => {
      active = false;
      window.removeEventListener('auth:unauthorized', markUnauthenticated);
    };
  }, []);

  if (state === 'checking') {
    return <div className="center">جارٍ التحقق من الجلسة...</div>;
  }

  if (state === 'unauthenticated') {
    return <Navigate to="/login" replace />;
  }

  return <Layout />;
}
