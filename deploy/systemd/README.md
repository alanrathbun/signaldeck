# systemd unit for SignalDeck

`signaldeck.service` is a systemd `--user` unit that runs SignalDeck under
supervision so the dashboard's Stop / Start / Restart controls have
something to talk to, and so a crash gets auto-restarted.

## Install

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/signaldeck.service ~/.config/systemd/user/signaldeck.service
systemctl --user daemon-reload
systemctl --user enable --now signaldeck.service
```

Verify:

```bash
systemctl --user status signaldeck.service
journalctl --user -u signaldeck.service -f
```

## Uninstall

```bash
systemctl --user disable --now signaldeck.service
rm ~/.config/systemd/user/signaldeck.service
systemctl --user daemon-reload
```

## Notes

- The unit uses `%h/signaldeck` as `WorkingDirectory`, so it expects the
  repo checked out at `~/signaldeck` and the venv at `~/signaldeck/.venv`.
  Adjust `WorkingDirectory` and `ExecStart` if your layout differs.
- The unit binds the dashboard to `0.0.0.0:9090` — matching the host/port
  this box has been using interactively. Port 8080 is reserved for
  `flight-monitor.service` on this host. If you want localhost-only access
  (safer default), change `--host 0.0.0.0` to `--host 127.0.0.1` in the
  `ExecStart` line.
- Because `--host 0.0.0.0` exposes the dashboard on the LAN, enable auth in
  `config/default.yaml` or `config/user_settings.yaml` — otherwise the
  process-control endpoints (`/api/process/{start,stop,restart}`) will
  refuse non-loopback callers (they return 403), which is safe but means
  the buttons won't work from a different machine until you turn on auth.
- `loginctl enable-linger $USER` lets the unit start at boot without an
  active desktop session.
