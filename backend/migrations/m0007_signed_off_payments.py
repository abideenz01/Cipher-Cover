"""A payment over the limit records who signed it off and when.

Since the claim agent pays after a sign-off, rather than the sign-off paying,
each payment keeps the sign-off it rests on. Payments under the limit have none.
"""

from backend import db

VERSION = 7
NAME = "signed_off_payments"


def upgrade(conn: db.Connection) -> None:
    """Add the handler who signed off a payment, and when."""
    for column in ("signed_off_by", "signed_off_at"):
        conn.execute(
            f"ALTER TABLE payments ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
        )
