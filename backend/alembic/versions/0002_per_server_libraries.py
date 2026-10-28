"""Split the library selection per media server

One instance can have Plex and Jellyfin configured at once, and two servers can
hold libraries of the same name, so a single media_libraries list could not say
what to scan where. The selection now lives under a key per server.

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

config = sa.table(
    "config",
    sa.column("id", sa.Integer),
    sa.column("key", sa.String),
    sa.column("value", sa.Text),
)

# A server is configured when these are present, which is also how the
# application decides it.
CREDENTIALS = {
    "plex": ("plex_auth_token",),
    "jellyfin": ("jellyfin_url", "jellyfin_api_key"),
}


def upgrade() -> None:
    bind = op.get_bind()
    rows = dict(bind.execute(sa.select(config.c.key, config.c.value)).all())

    selection = rows.get("media_libraries")
    if not selection:
        return

    # The old list did not record which server a library belonged to, so give
    # it to each configured server; the user can narrow it afterwards.
    for server, keys in CREDENTIALS.items():
        if not all(rows.get(key) for key in keys):
            continue

        key = f"{server}_libraries"
        if rows.get(key):
            continue

        bind.execute(config.insert().values(key=key, value=selection))

    bind.execute(config.delete().where(config.c.key == "media_libraries"))


def downgrade() -> None:
    bind = op.get_bind()
    rows = dict(bind.execute(sa.select(config.c.key, config.c.value)).all())

    merged = sorted(
        {
            name.strip()
            for server in CREDENTIALS
            for name in (rows.get(f"{server}_libraries") or "").split(",")
            if name.strip()
        }
    )
    if merged:
        bind.execute(
            config.insert().values(key="media_libraries", value=",".join(merged))
        )

    for server in CREDENTIALS:
        bind.execute(config.delete().where(config.c.key == f"{server}_libraries"))
