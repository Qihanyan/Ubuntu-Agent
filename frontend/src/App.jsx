import { useState, useRef, useEffect, useCallback } from 'react';
import './App.css';

const WS_URL = `wss://${window.location.host}/ws/chat`;
const TOKEN_KEY = 'music_agent_token';
const AUTH_FAILED_CODE = 4401;

function loadToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

function saveToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // 无痕模式等情况下存储不可用，只是下次需要重新登录
  }
}

function LoginForm({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username || !password || loading) return;
    setLoading(true);
    setError('');
    try {
      const resp = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        // 422（参数校验失败）时 detail 是数组，只显示字符串形式的错误
        setError(typeof data.detail === 'string' ? data.detail : '用户名或密码格式不正确');
        return;
      }
      onLogin(data.token);
    } catch {
      setError('无法连接服务器');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-container">
      <header className="chat-header">
        <h1>音乐管家</h1>
      </header>
      <form className="login-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="用户名"
          autoComplete="username"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="密码"
          autoComplete="current-password"
        />
        {error && <div className="login-error">{error}</div>}
        <button type="submit" disabled={loading}>
          {loading ? '登录中...' : '登录'}
        </button>
      </form>
    </div>
  );
}

function Chat({ token, onLogout }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [status, setStatus] = useState('');
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    // 第一条消息必须是鉴权消息，收到 auth_ok 后才算连上
    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }));
    ws.onclose = (event) => {
      setConnected(false);
      if (event.code === AUTH_FAILED_CODE) onLogout();
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'auth_ok') {
        setConnected(true);
      } else if (data.type === 'status') {
        setStatus(data.content);
      } else if (data.type === 'message' || data.type === 'error') {
        setMessages((prev) => [...prev, { role: 'assistant', content: data.content }]);
        setStatus('');
      }
    };

    return () => ws.close();
  }, [token, onLogout]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, status]);

  const handleSend = () => {
    if (!input.trim() || !connected || !wsRef.current) return;
    setMessages((prev) => [...prev, { role: 'user', content: input }]);
    wsRef.current.send(input);
    setInput('');
  };

  return (
    <div className="chat-container">
      <header className="chat-header">
        <h1>音乐管家</h1>
        <span className={`status-dot ${connected ? 'online' : 'offline'}`} />
        <button className="logout-button" onClick={onLogout}>退出</button>
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
          placeholder={connected ? '输入歌曲名称或跟我聊聊天...' : '正在连接...'}
        />
        <button onClick={handleSend} disabled={!connected}>发送</button>
      </div>
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(loadToken);

  const handleLogin = (newToken) => {
    saveToken(newToken);
    setToken(newToken);
  };

  // 保持引用稳定，避免 Chat 的 useEffect 因为 onLogout 变化而重连
  const handleLogout = useCallback(() => {
    saveToken('');
    setToken('');
  }, []);

  if (!token) return <LoginForm onLogin={handleLogin} />;
  return <Chat token={token} onLogout={handleLogout} />;
}
