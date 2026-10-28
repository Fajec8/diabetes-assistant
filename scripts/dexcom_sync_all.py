from sqlalchemy import select

from app.database import SessionLocal
from app.models.dexcom import (
    DexcomConnection,
)
from app.services.dexcom_sync import (
    sync_connection,
)


def main():
    synced = 0
    failed = 0
    inserted_total = 0

    with SessionLocal() as db:
        connections = (
            db.scalars(
                select(
                    DexcomConnection
                )
                .where(
                    DexcomConnection.active
                    .is_(
                        True
                    )
                )
            )
            .all()
        )

        for connection in connections:
            try:
                result = sync_connection(
                    db,
                    connection,
                )

                synced += 1

                inserted_total += (
                    result[
                        "records_inserted"
                    ]
                )

            except Exception:
                failed += 1

    print(
        "Dexcom sync finished:"
    )

    print(
        f"connections_ok={synced}"
    )

    print(
        f"connections_failed={failed}"
    )

    print(
        (
            "new_readings="
            f"{inserted_total}"
        )
    )


if __name__ == "__main__":
    main()