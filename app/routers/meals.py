import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import (
    Session,
    selectinload,
)

from app.database import get_db
from app.models.meal import Meal
from app.models.meal_item import MealItem
from app.models.user import User
from app.schemas.meal import (
    MealBolusAnalysisResponse,
    MealCreate,
    MealResponse,
)
from app.services.meal_bolus_analysis import (
    analyze_meal_bolus,
)


router = APIRouter(
    prefix="/meals",
    tags=["Meals"]
)


@router.post(
    "",
    response_model=MealResponse,
    status_code=status.HTTP_201_CREATED
)
def create_meal(
    data: MealCreate,
    db: Session = Depends(get_db)
):
    user = db.get(
        User,
        data.user_id
    )

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    meal = Meal(
        user_id=data.user_id,
        eaten_at=data.eaten_at,
        carbohydrates_g=data.carbohydrates_g,
        description=data.description,
        note=data.note
    )

    db.add(
        meal
    )

    db.flush()

    for item_data in data.items:
        item = MealItem(
            meal_id=meal.id,
            food_name=item_data.food_name,
            preparation=item_data.preparation,
            variant=item_data.variant,
            amount_g=item_data.amount_g,
            carbohydrates_g=(
                item_data.carbohydrates_g
            ),
            note=item_data.note
        )

        db.add(
            item
        )

    db.commit()

    statement = (
        select(
            Meal
        )
        .options(
            selectinload(
                Meal.items
            )
        )
        .where(
            Meal.id
            == meal.id
        )
    )

    created_meal = db.scalar(
        statement
    )

    return created_meal


@router.get(
    "/{meal_id}/bolus-analysis",
    response_model=MealBolusAnalysisResponse
)
def get_meal_bolus_analysis(
    meal_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    result = (
        analyze_meal_bolus(
            db=db,
            meal_id=meal_id
        )
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Meal not found"
        )

    return result