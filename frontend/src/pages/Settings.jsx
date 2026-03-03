import { useEffect, useState } from 'react';
import { Copy, Key, Shield } from 'lucide-react';
import { api } from '../lib/api';
import toast from 'react-hot-toast';

export default function Settings() {
  const [settings, setSettings] = useState(null);
  const [pwForm, setPwForm] = useState({ old_password: '', new_password: '' });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getSettings().then(setSettings).catch(console.error);
  }, []);

  const copy = (text) => {
    navigator.clipboard.writeText(text);
    toast.success('Copied!');
  };

  const handlePassword = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.changePassword(pwForm);
      toast.success('Password changed');
      setPwForm({ old_password: '', new_password: '' });
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleSecretChange = async () => {
    const secret = prompt('New agent secret:');
    if (!secret) return;
    try {
      await api.changeAgentSecret(secret);
      toast.success('Agent secret updated');
      api.getSettings().then(setSettings);
    } catch (err) {
      toast.error(err.message);
    }
  };

  if (!settings) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-claw-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Change Password */}
        <div className="bg-claw-card border border-claw-border rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Key size={18} className="text-claw-accent" />
            <h2 className="font-semibold">Change Password</h2>
          </div>
          <form onSubmit={handlePassword} className="space-y-3">
            <div>
              <label className="block text-sm text-claw-muted mb-1">Current Password</label>
              <input type="password" required value={pwForm.old_password}
                onChange={(e) => setPwForm({ ...pwForm, old_password: e.target.value })}
                className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-claw-accent" />
            </div>
            <div>
              <label className="block text-sm text-claw-muted mb-1">New Password</label>
              <input type="password" required minLength={6} value={pwForm.new_password}
                onChange={(e) => setPwForm({ ...pwForm, new_password: e.target.value })}
                className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-claw-accent" />
            </div>
            <button type="submit" disabled={saving}
              className="w-full bg-claw-accent hover:bg-claw-accent-hover text-white py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50">
              {saving ? 'Saving...' : 'Update Password'}
            </button>
          </form>
        </div>

        {/* Agent Secret */}
        <div className="bg-claw-card border border-claw-border rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Shield size={18} className="text-claw-green" />
            <h2 className="font-semibold">Agent Secret</h2>
          </div>
          <p className="text-xs text-claw-muted mb-3">Shared secret for node agents to authenticate with the panel.</p>
          <div className="flex items-center gap-2 bg-claw-bg rounded-lg px-3 py-2 mb-3">
            <code className="text-xs flex-1 truncate">{settings.agent_secret}</code>
            <button onClick={() => copy(settings.agent_secret)} className="text-claw-muted hover:text-claw-accent shrink-0">
              <Copy size={14} />
            </button>
          </div>
          <button onClick={handleSecretChange}
            className="w-full border border-claw-border hover:border-claw-accent text-claw-muted hover:text-claw-accent py-2 rounded-lg text-sm transition-colors">
            Change Secret
          </button>
        </div>

        {/* System Info */}
        <div className="bg-claw-card border border-claw-border rounded-xl p-5 lg:col-span-2">
          <h2 className="font-semibold mb-3">System Info</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div className="bg-claw-bg rounded-lg px-3 py-2">
              <span className="text-claw-muted text-xs">Panel Version</span>
              <div>v2.1.0</div>
            </div>
            <div className="bg-claw-bg rounded-lg px-3 py-2">
              <span className="text-claw-muted text-xs">Xray Build</span>
              <div>finalmask 26.2.6</div>
            </div>
            <div className="bg-claw-bg rounded-lg px-3 py-2">
              <span className="text-claw-muted text-xs">Protocols</span>
              <div>XHTTP \u00b7 HY2 \u00b7 XDNS \u00b7 XICMP</div>
            </div>
            <div className="bg-claw-bg rounded-lg px-3 py-2">
              <span className="text-claw-muted text-xs">Architecture</span>
              <div>Router \u2192 Node</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
