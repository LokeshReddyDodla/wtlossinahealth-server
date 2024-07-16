from lib.schemas.meal import FoodDescription
from rest_server.response_models import SuccessResponse


class MealAnalysisResponse(SuccessResponse):
    data: FoodDescription
