# ClawPanel — Operations & Debugging

## When to use
User needs help troubleshooting, managing users/nodes, or operating ClawPanel.

## Architecture
```
Panel (router) ←60s→ Agent (node1)
                ←60s→ Agent (node2)
                      ...

Panel generates xray-hy config → Agent pulls → writes → restarts xray-hy
Agent sends traffic stats with --reset (delta-based) → Panel accumulates
```

## Common Operations

### Add user via API
```bash
curl -X POST http://127.0.0.1:3100/api/users \
  -H "Content-Type: application/json" \
  -b <cookie> \
  -d '{"username":"alice","data_limit_gb":50,"expire_days":30}'
```

### Toggle user protocols
```bash
curl -X POST http://127.0.0.1:3100/api/users/{id}/protocols \
  -H "Content-Type: application/json" \
  -b <cookie> \
  -d '{"enabled_protocols":"exit,direct"}'
# Valid: exit, direct, dns, icmp
```

### Force config sync on node
```bash
ssh root@node "systemctl restart claw-agent"
```

### Test proxy via curl
```bash
# Create xray client config
cat > /tmp/test.json << 'EOF'
{
  "inbounds": [{"tag":"socks","port":10808,"protocol":"socks","settings":{"udp":true}}],
  "outbounds": [{"protocol":"vless","settings":{"vnext":[{"address":"NODE_IP","port":443,"users":[{"id":"USER_UUID","encryption":"none"}]}]},"streamSettings":{"network":"xhttp","xhttpSettings":{"mode":"auto"},"security":"tls","tlsSettings":{"serverName":"NODE_DOMAIN","alpn":["h2","http/1.1"]}}}]
}
EOF
xray-hy run -c /tmp/test.json &
curl -x socks5h://127.0.0.1:10808 https://api.ipify.org
```

### Check xray stats
```bash
xray-hy api statsquery --server=127.0.0.1:10085 --pattern=user --reset
```

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| xray-hy crash loop | Wrong cert path | Check `journalctl -u claw-xray-hy`, fix cert paths in panel .env |
| No corp exit IP | CORP_EXIT_* env vars missing | Add to /opt/clawpanel/.env, restart panel |
| Node offline | Agent secret mismatch | Check /etc/claw-agent/env matches panel Settings |
| Sub returns 403 | User disabled/expired/over limit | Check user status in panel |
| Traffic not counting | Missing stats/api/policy in xray config | Check xray.py has stats sections |
| Emoji garbled in sub | DB encoding issue | Use Unicode escapes in Python, not DB-stored emoji |

## File Locations

### Panel server
- Code: `/opt/clawpanel/`
- DB: `/opt/clawpanel/data/claw.db`
- Env: `/opt/clawpanel/.env`
- Service: `clawpanel.service`
- Caddy: `/etc/caddy/Caddyfile`

### Node server
- Agent: `/opt/claw-agent/agent.py`
- Agent env: `/etc/claw-agent/env`
- Xray config: `/etc/claw-xray-hy/config.json`
- Xray binary: `/usr/local/bin/xray-hy`
- Services: `claw-agent.service`, `claw-xray-hy.service`

## CRITICAL: Don't break running nodes
- NEVER change cert paths without testing first
- NEVER restart xray-hy directly — let the agent handle it
- ALWAYS verify config generation before deploying: check `/agent/config/{name}` output
- Test with curl proxy BEFORE telling user it's done
