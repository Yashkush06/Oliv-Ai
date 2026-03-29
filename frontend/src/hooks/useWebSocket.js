import { useState, useEffect, useRef } from 'react';

/**
 * Hook to manage a WebSocket connection and return the latest messages.
 * Handles React StrictMode double-mounting safely.
 */
export function useWebSocket(url) {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState('disconnected');
  const wsRef = useRef(null);

  useEffect(() => {
    let destroyed = false;      // Prevents zombie reconnections after cleanup
    let socket = null;
    let pingInterval = null;
    let reconnectTimeout = null;

    const connect = () => {
      if (destroyed) return;    // Don't connect if already cleaned up
      
      setStatus('connecting');
      socket = new WebSocket(url);
      wsRef.current = socket;
      
      socket.onopen = () => {
        if (destroyed) { socket.close(); return; }
        setStatus('connected');
        pingInterval = setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send('ping');
          }
        }, 15000);
      };

      socket.onmessage = (event) => {
        if (destroyed) return;
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'pong') return;
          setMessages(prev => [...prev, data]);
        } catch (e) {
          console.error("Failed to parse WS message", e);
        }
      };

      socket.onclose = () => {
        setStatus('disconnected');
        if (pingInterval) { clearInterval(pingInterval); pingInterval = null; }
        // Only reconnect if not intentionally destroyed
        if (!destroyed) {
          reconnectTimeout = setTimeout(connect, 3000);
        }
      };

      socket.onerror = (error) => {
        console.error('WebSocket error:', error);
      };
    };

    connect();

    return () => {
      destroyed = true;         // Prevent any future reconnections
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (pingInterval) clearInterval(pingInterval);
      if (socket) socket.close();
      wsRef.current = null;
    };
  }, [url]);

  const clearMessages = () => setMessages([]);
  
  const sendMessage = (msgObj) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msgObj));
    }
  };

  return { messages, status, clearMessages, sendMessage };
}
