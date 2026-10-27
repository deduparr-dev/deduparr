"""Name the media server explicitly on duplicate sets and deletion history

Deduparr used to assume Plex, so the schema said plex_item_id and
plex_refreshed. Now that an instance can have Plex and Jellyfin configured at
once, a set records which server reported it and the columns are named for the
concept rather than one implementation.

This is the first migration in the project: the schema used to come from
Base.metadata.create_all, so it has to cope with a database that already has
tables as well as a fresh one. Later migrations can be ordinary explicit DDL.

Revision ID: 0001
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.database import Base

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "duplicate_sets" not in inspector.get_table_names():
        # Fresh install: the models already describe the current schema.
        Base.metadata.create_all(bind=bind)
        return

    set_columns = {column["name"] for column in inspector.get_columns("duplicate_sets")}
    with op.batch_alter_table("duplicate_sets") as batch:
        if "plex_item_id" in set_columns and "item_id" not in set_columns:
            batch.alter_column("plex_item_id", new_column_name="item_id")
        if "media_server" not in set_columns:
            batch.add_column(
                sa.Column(
                    "media_server",
                    sa.String(32),
                    nullable=False,
                    server_default="plex",
                )
            )

    history_columns = {
        column["name"] for column in inspector.get_columns("deletion_history")
    }
    if (
        "plex_refreshed" in history_columns
        and "media_server_refreshed" not in history_columns
    ):
        with op.batch_alter_table("deletion_history") as batch:
            batch.alter_column(
                "plex_refreshed", new_column_name="media_server_refreshed"
            )


def downgrade() -> None:
    with op.batch_alter_table("deletion_history") as batch:
        batch.alter_column("media_server_refreshed", new_column_name="plex_refreshed")
    with op.batch_alter_table("duplicate_sets") as batch:
        batch.drop_column("media_server")
        batch.alter_column("item_id", new_column_name="plex_item_id")
