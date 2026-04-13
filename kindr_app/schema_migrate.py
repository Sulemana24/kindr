"""Lightweight SQLite column additions for existing databases."""

from sqlalchemy import inspect, text

from kindr_app.extensions import db


def run_schema_migrate(app) -> None:
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    if not uri.startswith("sqlite"):
        return
    with app.app_context():
        insp = inspect(db.engine)
        if not insp.has_table("campaigns"):
            return
        cols_users = {c["name"] for c in insp.get_columns("users")}
        if "is_admin" not in cols_users:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0 NOT NULL"))
                conn.commit()
        insp = inspect(db.engine)
        cols_users = {c["name"] for c in insp.get_columns("users")}
        if "is_suspended" not in cols_users:
            with db.engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN is_suspended BOOLEAN DEFAULT 0 NOT NULL")
                )
                conn.commit()
        insp = inspect(db.engine)
        cols_c = {c["name"] for c in insp.get_columns("campaigns")}
        if "raised_amount" not in cols_c:
            with db.engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE campaigns ADD COLUMN raised_amount FLOAT DEFAULT 0 NOT NULL")
                )
                conn.commit()
        insp = inspect(db.engine)
        cols_c = {c["name"] for c in insp.get_columns("campaigns")}
        if "donor_count" not in cols_c:
            with db.engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE campaigns ADD COLUMN donor_count INTEGER DEFAULT 0 NOT NULL")
                )
                conn.commit()
        insp = inspect(db.engine)
        cols_c = {c["name"] for c in insp.get_columns("campaigns")}
        if "status" not in cols_c:
            with db.engine.connect() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE campaigns ADD COLUMN status TEXT DEFAULT 'pending_review' NOT NULL"
                    )
                )
                conn.commit()
        insp = inspect(db.engine)
        cols_c = {c["name"] for c in insp.get_columns("campaigns")}
        if "start_date" not in cols_c:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE campaigns ADD COLUMN start_date DATETIME"))
                conn.commit()
        insp = inspect(db.engine)
        cols_c = {c["name"] for c in insp.get_columns("campaigns")}
        if "end_date" not in cols_c:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE campaigns ADD COLUMN end_date DATETIME"))
                conn.commit()
        insp = inspect(db.engine)
        cols_c = {c["name"] for c in insp.get_columns("campaigns")}
        if "is_closed" not in cols_c:
            with db.engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE campaigns ADD COLUMN is_closed BOOLEAN DEFAULT 0 NOT NULL")
                )
                conn.commit()
        insp = inspect(db.engine)
        cols_c = {c["name"] for c in insp.get_columns("campaigns")}
        if "withdrawal_requested_at" not in cols_c:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE campaigns ADD COLUMN withdrawal_requested_at DATETIME"))
                conn.commit()
        insp = inspect(db.engine)
        cols_c = {c["name"] for c in insp.get_columns("campaigns")}
        if "withdrawal_fee_amount" not in cols_c:
            with db.engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE campaigns ADD COLUMN withdrawal_fee_amount FLOAT DEFAULT 0 NOT NULL")
                )
                conn.commit()
        insp = inspect(db.engine)
        cols_c = {c["name"] for c in insp.get_columns("campaigns")}
        if "withdrawal_net_amount" not in cols_c:
            with db.engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE campaigns ADD COLUMN withdrawal_net_amount FLOAT DEFAULT 0 NOT NULL")
                )
                conn.commit()
