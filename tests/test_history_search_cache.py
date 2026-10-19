from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.services.history_search import (
    _HistorySituationCache,
)
from app.services.situation_builder import (
    build_situation,
)


def test_cached_situation_matches_normal_builder():
    db = SessionLocal()

    try:
        user = db.scalar(
            select(User).where(
                User.email
                == "test@example.com"
            )
        )

        assert user is not None

        timezone = ZoneInfo(
            "Europe/Prague"
        )

        search_t0 = datetime(
            2026,
            10,
            3,
            13,
            30,
            tzinfo=timezone
        )

        cache = (
            _HistorySituationCache(
                db=db,
                user_id=user.id,
                search_t0=
                    search_t0
            )
        )

        test_times = [
            datetime(
                2026,
                9,
                28,
                13,
                30,
                tzinfo=timezone
            ),

            datetime(
                2026,
                9,
                30,
                13,
                0,
                tzinfo=timezone
            ),

            datetime(
                2026,
                10,
                2,
                13,
                30,
                tzinfo=timezone
            ),

            search_t0
        ]

        for t0 in test_times:
            normal = (
                build_situation(
                    db=db,
                    user_id=user.id,
                    t0=t0
                )
            )

            cached = (
                cache.build_situation(
                    t0=t0,
                    timezone=timezone
                )
            )

            assert (
                cached
                == normal
            )

    finally:
        db.close()