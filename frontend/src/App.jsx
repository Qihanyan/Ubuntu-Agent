import React, { useState, useRef, useEffect } from 'react';
import './App.css';

const WS_URL = `wss://${window.location.host}/ws/chat`;

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [status, setStatus] = useState('');
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'status') {
        setStatus(data.content);
      } else if (data.type === 'message') {
        setMessages((prev) => [...prev, { role: 'assistant', content: data.content }]);
        setStatus('');
      }
    };

    return () => ws.close();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, status]);

  const handleSend = () => {
    if (!input.trim() || !wsRef.current) return;
    setMessages((prev) => [...prev, { role: 'user', content: input }]);
    wsRef.current.send(input);
    setInput('');
  };

  return (
    <div className="chat-container">
      <header className="chat-header">
        <h1>音乐管家</h1>
        <span className={`status-dot ${connected ? 'online' : 'offline'}`} />
      </header>

      <div className="messages-area">
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role}`}>
            {msg.content}
          </div>
        ))}
        {status && <div className="status-indicator">{status}</div>}
        <div ref={messagesEndRef} />
      </div>

      <div className="input-area">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="输入歌曲名称或跟我聊聊天..."
        />
        <button onClick={handleSend}>发送</button>
      </div>
    </div>
  );
}