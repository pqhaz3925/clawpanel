const BASE = '';

async function request(url, opts = {}) {
  const res = await fetch(BASE + url, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  });
  if (res.status === 401) {
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

export const api = {
  // Auth
  login: (username, password) =>
    fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json()).detail || 'Login failed');
      return r.json();
    }),
  logout: () => fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }),
  me: () => request('/api/auth/me'),

  // Dashboard
  stats: () => request('/api/stats'),

  // Users
  getUsers: () => request('/api/users'),
  createUser: (data) => request('/api/users', { method: 'POST', body: JSON.stringify(data) }),
  updateUser: (id, data) => request(`/api/users/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteUser: (id) => request(`/api/users/${id}`, { method: 'DELETE' }),
  toggleUser: (id) => request(`/api/users/${id}/toggle`, { method: 'POST' }),
  resetTraffic: (id) => request(`/api/users/${id}/reset-traffic`, { method: 'POST' }),
  resetUuid: (id) => request(`/api/users/${id}/reset-uuid`, { method: 'POST' }),
  getUserSub: (id) => request(`/api/users/${id}/sub-info`),
  updateProtocols: (id, protocols) =>
    request(`/api/users/${id}/protocols`, { method: 'POST', body: JSON.stringify({ enabled_protocols: protocols }) }),

  // Nodes
  getNodes: () => request('/api/nodes'),
  createNode: (data) => request('/api/nodes', { method: 'POST', body: JSON.stringify(data) }),
  deleteNode: (id) => request(`/api/nodes/${id}`, { method: 'DELETE' }),
  toggleNode: (id) => request(`/api/nodes/${id}/toggle`, { method: 'POST' }),

  // Settings
  getSettings: () => request('/api/settings'),
  changePassword: (data) => request('/api/settings/password', { method: 'POST', body: JSON.stringify(data) }),
  changeAgentSecret: (secret) =>
    request('/api/settings/agent-secret', { method: 'POST', body: JSON.stringify({ agent_secret: secret }) }),
};
