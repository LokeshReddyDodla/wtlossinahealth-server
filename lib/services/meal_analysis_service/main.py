from fastapi import FastAPI, HTTPException
from schemas import MealAnalysisRequest, MealAnalysisResult
from service import MealAnalysisService

app = FastAPI()

# Initialize the service
meal_analysis_service = MealAnalysisService()


@app.post("/analyze", response_model=MealAnalysisResult)
async def analyze_meal(request: MealAnalysisRequest):
    try:
        result = await meal_analysis_service.analyze_meal(
            context=request.context,
            meal_time=request.meal_time,
            meal_type=request.meal_type,
            image_url=request.image_url,
            meal_description=request.meal_description,
            update_fields=request.update_fields,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
