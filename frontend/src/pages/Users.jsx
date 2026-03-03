import { useEffect, useState, useCallback } from 'react';
import { Plus, Copy, Trash2, RotateCcw, Power, Link2, Eye, Check } from 'lucide-react';
import { api } from '../lib/api';
import toast from 'react-hot-toast';
import Modal from '../components/Modal';

function formatBytes(b) {
  if (!b) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (Math.abs(b) >= 1024 && i < units.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(1)} ${units[i]}`;
}

function statusBadge(user) {
  if (!user.is_active) return { text: 'disabled', cls: 'bg-claw-red/15 text-claw-red' };
  if (user.expire_at > 0 && user.expire_at < Date.now() / 1000) return { text: 'expired', cls: 'bg-claw-amber/15 text-claw-amber' };
  if (user.data_limit > 0 && user.data_used >= user.data_limit) return { text: 'limit', cls: 'bg-claw-amber/15 text-claw-amber' };
  return { text: 'active', cls: 'bg-claw-green/15 text-claw-green' };
}

function timeLeft(ts) {
  if (!ts) return '\u221e';
  const diff = ts - Date.now() / 1000;
  if (diff <= 0) return 'expired';
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

export default function Users() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [subOpen, setSubOpen] = useState(null); // user id
  const [subData, setSubData] = useState(null);
  const [editOpen, setEditOpen] = useState(null); // user object

  const load = useCallback(() => {
    api.getUsers().then((d) => { setUsers(d.users); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleToggle = async (id) => {
    await api.toggleUser(id);
    toast.success('User toggled');
    load();
  };

  const handleDelete = async (id, username) => {
    if (!confirm(`Delete user "${username}"?`)) return;
    await api.deleteUser(id);
    toast.success('User deleted');
    load();
  };

  const handleResetTraffic = async (id) => {
    await api.resetTraffic(id);
    toast.success('Traffic reset');
    load();
  };

  const handleResetUuid = async (id) => {
    if (!confirm('Reset UUID? Existing connections will break.')) return;
    await api.resetUuid(id);
    toast.success('UUID reset');
    load();
  };

  const openSub = async (id) => {
    setSubOpen(id);
    setSubData(null);
    try {
      const d = await api.getUserSub(id);
      setSubData(d);
    } catch {
      toast.error('Failed to load subscription');
      setSubOpen(null);
    }
  };

  const copy = (text) => {
    navigator.clipboard.writeText(text);
    toast.success('Copied!');
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-claw-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Users</h1>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 bg-claw-accent hover:bg-claw-accent-hover text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          <Plus size={16} /> Create User
        </button>
      </div>

      {/* Users table */}
      <div className="bg-claw-card border border-claw-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-claw-border text-claw-muted text-left">
              <th className="px-4 py-3 font-medium">Username</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Traffic</th>
              <th className="px-4 py-3 font-medium">Expires</th>
              <th className="px-4 py-3 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const st = statusBadge(u);
              return (
                <tr key={u.id} className="border-b border-claw-border/50 hover:bg-claw-border/10 transition-colors">
                  <td className="px-4 py-3 font-medium">{u.username}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${st.cls}`}>{st.text}</span>
                  </td>
                  <td className="px-4 py-3 text-claw-muted">
                    {formatBytes(u.data_used)}
                    {u.data_limit > 0 && <span className="text-claw-border"> / {formatBytes(u.data_limit)}</span>}
                  </td>
                  <td className="px-4 py-3 text-claw-muted">{timeLeft(u.expire_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1 justify-end">
                      <button onClick={() => openSub(u.id)} className="p-1.5 rounded-lg hover:bg-claw-border/30 text-claw-muted hover:text-claw-accent transition-colors" title="Subscription">
                        <Link2 size={15} />
                      </button>
                      <button onClick={() => setEditOpen(u)} className="p-1.5 rounded-lg hover:bg-claw-border/30 text-claw-muted hover:text-claw-text transition-colors" title="Edit">
                        <Eye size={15} />
                      </button>
                      <button onClick={() => handleToggle(u.id)} className="p-1.5 rounded-lg hover:bg-claw-border/30 text-claw-muted hover:text-claw-amber transition-colors" title="Toggle">
                        <Power size={15} />
                      </button>
                      <button onClick={() => handleResetTraffic(u.id)} className="p-1.5 rounded-lg hover:bg-claw-border/30 text-claw-muted hover:text-claw-green transition-colors" title="Reset traffic">
                        <RotateCcw size={15} />
                      </button>
                      <button onClick={() => handleDelete(u.id, u.username)} className="p-1.5 rounded-lg hover:bg-claw-border/30 text-claw-muted hover:text-claw-red transition-colors" title="Delete">
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {users.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-claw-muted">No users yet</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Create User Modal */}
      <CreateUserModal open={createOpen} onClose={() => setCreateOpen(false)} onCreated={load} />

      {/* Subscription Modal */}
      <SubModal open={!!subOpen} onClose={() => setSubOpen(null)} data={subData} onCopy={copy} />

      {/* Edit User Modal */}
      <EditUserModal user={editOpen} onClose={() => setEditOpen(null)} onSaved={load} onResetUuid={handleResetUuid} onCopy={copy} />
    </div>
  );
}

function CreateUserModal({ open, onClose, onCreated }) {
  const [form, setForm] = useState({ username: '', data_limit_gb: 0, expire_days: 0, note: '' });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.createUser(form);
      toast.success('User created');
      setForm({ username: '', data_limit_gb: 0, expire_days: 0, note: '' });
      onClose();
      onCreated();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Create User">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm text-claw-muted mb-1">Username</label>
          <input type="text" required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
            className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-claw-accent" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm text-claw-muted mb-1">Data Limit (GB)</label>
            <input type="number" step="0.1" min="0" value={form.data_limit_gb} onChange={(e) => setForm({ ...form, data_limit_gb: parseFloat(e.target.value) || 0 })}
              className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-claw-accent" />
            <span className="text-xs text-claw-muted">0 = unlimited</span>
          </div>
          <div>
            <label className="block text-sm text-claw-muted mb-1">Expire (days)</label>
            <input type="number" min="0" value={form.expire_days} onChange={(e) => setForm({ ...form, expire_days: parseInt(e.target.value) || 0 })}
              className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-claw-accent" />
            <span className="text-xs text-claw-muted">0 = never</span>
          </div>
        </div>
        <div>
          <label className="block text-sm text-claw-muted mb-1">Note</label>
          <input type="text" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })}
            className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-claw-accent" />
        </div>
        <button type="submit" disabled={saving}
          className="w-full bg-claw-accent hover:bg-claw-accent-hover text-white py-2.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-50">
          {saving ? 'Creating...' : 'Create'}
        </button>
      </form>
    </Modal>
  );
}

function EditUserModal({ user, onClose, onSaved, onResetUuid, onCopy }) {
  const PROTOS = [
    { key: 'exit', label: 'VLESS EXIT', color: 'text-claw-accent' },
    { key: 'direct', label: 'VLESS DIRECT', color: 'text-claw-green' },
    { key: 'dns', label: 'HY2 DNS', color: 'text-claw-amber' },
    { key: 'icmp', label: 'HY2 ICMP', color: 'text-claw-red' },
  ];

  const [protos, setProtos] = useState(new Set());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (user) {
      const ep = user.enabled_protocols || 'exit,direct,dns,icmp';
      setProtos(new Set(ep.split(',').map(p => p.trim())));
    }
  }, [user]);

  if (!user) return null;

  const toggleProto = async (key) => {
    const next = new Set(protos);
    if (next.has(key)) next.delete(key); else next.add(key);
    if (next.size === 0) { toast.error('Need at least 1 protocol'); return; }
    setSaving(true);
    try {
      await api.updateProtocols(user.id, [...next].join(','));
      setProtos(next);
      toast.success('Protocols updated');
      onSaved();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={!!user} onClose={onClose} title={`User: ${user.username}`}>
      <div className="space-y-3 text-sm">
        <div className="flex items-center justify-between bg-claw-bg rounded-lg px-3 py-2">
          <span className="text-claw-muted">UUID</span>
          <div className="flex items-center gap-2">
            <code className="text-xs">{user.xray_uuid?.slice(0, 18)}...</code>
            <button onClick={() => onCopy(user.xray_uuid)} className="text-claw-muted hover:text-claw-accent"><Copy size={14} /></button>
          </div>
        </div>
        <div className="flex items-center justify-between bg-claw-bg rounded-lg px-3 py-2">
          <span className="text-claw-muted">Status</span>
          <span className={user.is_active ? 'text-claw-green' : 'text-claw-red'}>{user.is_active ? 'Active' : 'Disabled'}</span>
        </div>
        <div className="flex items-center justify-between bg-claw-bg rounded-lg px-3 py-2">
          <span className="text-claw-muted">Traffic</span>
          <span>{formatBytes(user.data_used)}{user.data_limit > 0 ? ` / ${formatBytes(user.data_limit)}` : ''}</span>
        </div>
        <div className="flex items-center justify-between bg-claw-bg rounded-lg px-3 py-2">
          <span className="text-claw-muted">Expires</span>
          <span>{timeLeft(user.expire_at)}</span>
        </div>
        {user.note && (
          <div className="flex items-center justify-between bg-claw-bg rounded-lg px-3 py-2">
            <span className="text-claw-muted">Note</span>
            <span>{user.note}</span>
          </div>
        )}

        {/* Protocol toggles */}
        <div className="bg-claw-bg rounded-lg px-3 py-3">
          <span className="text-claw-muted text-xs block mb-2">Subscription Protocols</span>
          <div className="grid grid-cols-2 gap-2">
            {PROTOS.map(({ key, label, color }) => (
              <button
                key={key}
                onClick={() => toggleProto(key)}
                disabled={saving}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                  protos.has(key)
                    ? `border-claw-accent/50 ${color} bg-claw-accent/10`
                    : 'border-claw-border text-claw-muted opacity-50'
                }`}
              >
                {protos.has(key) ? '\u2713 ' : ''}{label}
              </button>
            ))}
          </div>
        </div>

        <button onClick={() => { onResetUuid(user.id); onClose(); }}
          className="w-full mt-2 border border-claw-border hover:border-claw-red text-claw-muted hover:text-claw-red py-2 rounded-lg text-sm transition-colors">
          Reset UUID
        </button>
      </div>
    </Modal>
  );
}

function SubModal({ open, onClose, data, onCopy }) {
  if (!data) {
    return (
      <Modal open={open} onClose={onClose} title="Subscription">
        <div className="flex items-center justify-center py-8">
          <div className="w-6 h-6 border-2 border-claw-accent border-t-transparent rounded-full animate-spin" />
        </div>
      </Modal>
    );
  }

  const linkColors = {
    EXIT: 'text-claw-accent',
    DIRECT: 'text-claw-green',
    DNS: 'text-claw-amber',
    ICMP: 'text-claw-red',
  };

  const getLinkColor = (link) => {
    for (const [key, cls] of Object.entries(linkColors)) {
      if (link.includes(key)) return cls;
    }
    return 'text-claw-text';
  };

  return (
    <Modal open={open} onClose={onClose} title="Subscription" wide>
      <div className="space-y-4">
        {/* Sub URL */}
        <div>
          <label className="text-sm text-claw-muted mb-1 block">Subscription URL</label>
          <div className="flex items-center gap-2 bg-claw-bg rounded-lg px-3 py-2">
            <code className="text-xs flex-1 truncate text-claw-accent">{data.sub_url}</code>
            <button onClick={() => onCopy(data.sub_url)} className="text-claw-muted hover:text-claw-accent shrink-0"><Copy size={14} /></button>
          </div>
        </div>

        {/* QR */}
        <div className="flex justify-center">
          <img src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(data.sub_url)}`}
            alt="QR" className="rounded-lg" />
        </div>

        {/* Individual links */}
        <div>
          <label className="text-sm text-claw-muted mb-2 block">Protocol Links</label>
          <div className="space-y-1.5">
            {data.links.map((link, i) => {
              const label = decodeURIComponent(link.split('#').pop() || '');
              return (
                <div key={i} className="flex items-center gap-2 bg-claw-bg rounded-lg px-3 py-2">
                  <span className={`text-xs font-medium flex-1 truncate ${getLinkColor(link)}`}>{label}</span>
                  <button onClick={() => onCopy(link)} className="text-claw-muted hover:text-claw-accent shrink-0"><Copy size={14} /></button>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Modal>
  );
}
