from lib.schemas.meal import MealDescription
from rest_server.response_models import SuccessResponse


class MealAnalysisResponse(SuccessResponse):
    data: MealDescription
