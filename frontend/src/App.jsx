import { Routes, Route, Navigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { api } from './lib/api';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Users from './pages/Users';
import Nodes from './pages/Nodes';
import Settings from './pages/Settings';

export default function App() {
  const [auth, setAuth] = useState(null); // null=loading, false=not logged in, string=admin
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    api.me()
      .then((d) => { setAuth(d.admin); setChecking(false); })
      .catch(() => { setAuth(false); setChecking(false); });
  }, []);

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-claw-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={auth ? <Navigate to="/" /> : <Login onLogin={setAuth} />} />
      <Route element={auth ? <Layout admin={auth} onLogout={() => setAuth(false)} /> : <Navigate to="/login" />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/users" element={<Users />} />
        <Route path="/nodes" element={<Nodes />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" />} />
    </Routes>
  );
}
