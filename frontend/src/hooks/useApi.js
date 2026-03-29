import axios from 'axios';
import { useState, useCallback } from 'react';

// Use same host as origin, but port 8000
const API_BASE = 'http://localhost:8000/api';

export const api = axios.create({
  baseURL: API_BASE,
});

export function useApi() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const request = useCallback(async (method, url, data = null) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api({ method, url, data });
      return res.data;
    } catch (err) {
      const msg = err.response?.data?.detail || err.response?.data?.message || err.message;
      setError(msg);
      throw new Error(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  return { request, loading, error };
}
