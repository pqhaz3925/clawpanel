import { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { api } from '../lib/api';
import toast from 'react-hot-toast';

export default function Login({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const data = await api.login(username, password);
      onLogin(data.admin);
    } catch (err) {
      toast.error(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold">
            <span className="text-claw-accent">Claw</span>Panel
          </h1>
          <p className="text-claw-muted text-sm mt-2">VPN Management Panel</p>
        </div>
        <form
          onSubmit={handleSubmit}
          className="bg-claw-card border border-claw-border rounded-2xl p-6 space-y-4"
        >
          <div>
            <label className="block text-sm text-claw-muted mb-1.5">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-claw-accent transition-colors"
            />
          </div>
          <div>
            <label className="block text-sm text-claw-muted mb-1.5">Password</label>
            <div className="relative">
              <input
                type={showPw ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2.5 text-sm pr-10 focus:outline-none focus:border-claw-accent transition-colors"
              />
              <button
                type="button"
                onClick={() => setShowPw(!showPw)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-claw-muted hover:text-claw-text"
              >
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-claw-accent hover:bg-claw-accent-hover text-white py-2.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            {loading ? 'Logging in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}
