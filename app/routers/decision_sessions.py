from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db

from app.schemas.decision import (
    ActionPlanCreate,
    ActionPlanResponse,
    DecisionOutcomeCreate,
    DecisionSessionCreate,
    DecisionSessionResponse,
)
from app.services.active_decision_session import (
    get_active_decision_session_id,
)
from app.services.cancel_decision_session import (
    cancel_decision_session,
)
from app.services.decision_sessions import (
    create_decision_outcome,
    create_decision_session,
    create_user_action_plan,
    get_decision_session,
)


router = APIRouter(
    prefix="/decision-sessions",
    tags=[
        "Decision Sessions"
    ],
)


SHADOW_HTML = (
    Path(__file__)
    .resolve()
    .parent
    .parent
    / "static"
    / "shadow.html"
)


def _error_message(
    exc: Exception,
) -> str:
    if (
        hasattr(
            exc,
            "args"
        )
        and exc.args
    ):
        return str(
            exc.args[0]
        )

    return str(
        exc
    )


@router.get(
    "/shadow",
    include_in_schema=False,
)
def shadow_ui():
    if not SHADOW_HTML.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                "Shadow UI file "
                "was not found"
            ),
        )

    return FileResponse(
        SHADOW_HTML,
        media_type="text/html",
    )


@router.post(
    "",
    response_model=
        DecisionSessionResponse,
    status_code=
        status.HTTP_201_CREATED,
)
def create_session(
    payload: DecisionSessionCreate,
    db: Session = Depends(
        get_db
    ),
):
    try:
        session = (
            create_decision_session(
                db=db,
                payload=payload,
            )
        )

        return get_decision_session(
            db=db,
            session_id=session.id,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=
                _error_message(
                    exc
                ),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail=
                _error_message(
                    exc
                ),
        ) from exc


@router.post(
    "/{session_id}/user-plan",
    response_model=
        ActionPlanResponse,
    status_code=
        status.HTTP_201_CREATED,
)
def create_user_plan(
    session_id: uuid.UUID,
    payload: ActionPlanCreate,
    db: Session = Depends(
        get_db
    ),
):
    try:
        return (
            create_user_action_plan(
                db=db,
                session_id=session_id,
                payload=payload,
            )
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=
                _error_message(
                    exc
                ),
        ) from exc

    except (
        RuntimeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail=
                _error_message(
                    exc
                ),
        ) from exc


@router.post(
    "/{session_id}/outcome",
    response_model=
        DecisionSessionResponse,
    status_code=
        status.HTTP_201_CREATED,
)
def create_outcome(
    session_id: uuid.UUID,
    payload: DecisionOutcomeCreate,
    db: Session = Depends(
        get_db
    ),
):
    try:
        create_decision_outcome(
            db=db,
            session_id=session_id,
            payload=payload,
        )

        return get_decision_session(
            db=db,
            session_id=session_id,
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=
                _error_message(
                    exc
                ),
        ) from exc

    except (
        RuntimeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail=
                _error_message(
                    exc
                ),
        ) from exc


@router.post(
    "/{session_id}/cancel",
    status_code=
        status.HTTP_204_NO_CONTENT,
)
def cancel_session(
    session_id: uuid.UUID,
    db: Session = Depends(
        get_db
    ),
):
    try:
        cancel_decision_session(
            db=db,
            session_id=session_id,
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=
                _error_message(
                    exc
                ),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail=
                _error_message(
                    exc
                ),
        ) from exc

    return Response(
        status_code=
            status.HTTP_204_NO_CONTENT
    )


@router.get(
    "/active/{user_id}",
    response_model=
        DecisionSessionResponse
        | None,
)
def read_active_session(
    user_id: uuid.UUID,
    db: Session = Depends(
        get_db
    ),
):
    session_id = (
        get_active_decision_session_id(
            db=db,
            user_id=user_id,
        )
    )

    if session_id is None:
        return None

    return get_decision_session(
        db=db,
        session_id=session_id,
    )


@router.get(
    "/{session_id}",
    response_model=
        DecisionSessionResponse,
)
def read_session(
    session_id: uuid.UUID,
    db: Session = Depends(
        get_db
    ),
):
    try:
        return get_decision_session(
            db=db,
            session_id=session_id,
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=
                _error_message(
                    exc
                ),
        ) from exc