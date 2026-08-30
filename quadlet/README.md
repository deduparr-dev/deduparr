# Podman quadlets — development

Systemd units that run the development stack under Podman, replacing the
former `docker-compose.dev.yml`.

## Requirements

- Podman **5.0+** (the `.build` units need it)
- A user systemd session (`systemctl --user`). Quadlets *are* systemd units —
  they do not work in a container without systemd.

## Install

Quadlets are read from a fixed directory, so symlink or copy them there:

```bash
mkdir -p ~/.config/containers/systemd
ln -sf "$PWD"/quadlet/*.{pod,build,container} ~/.config/containers/systemd/
systemctl --user daemon-reload
```

If the checkout is not at `/workspaces/deduparr`, edit the `File=` and
`Volume=` paths first — they are absolute, and each file marks them
`REPO_ROOT`.

## Run

```bash
systemctl --user start deduparr-frontend.service
```

The frontend `Requires=` the backend, which in turn pulls in the pod, so that
one command starts everything. Both images build on first start.

- frontend → http://localhost:3000
- backend  → http://localhost:3001

## Everyday use

```bash
systemctl --user status  deduparr-backend.service
journalctl --user -u     deduparr-frontend.service -f
systemctl --user stop    deduparr-frontend.service deduparr-backend.service
podman pod ps
```

Rebuild after changing a Containerfile or dependency:

```bash
systemctl --user stop deduparr-frontend.service deduparr-backend.service
podman rmi localhost/deduparr-backend-dev:latest localhost/deduparr-frontend-dev:latest
systemctl --user start deduparr-frontend.service
```

Application source is bind-mounted, so ordinary code edits hot-reload without
a rebuild.

## Notes

Both containers share the pod's network namespace, so the frontend reaches the
backend on `127.0.0.1:3001` rather than by service name as it did under
Compose. Ports are published once, on the pod.
