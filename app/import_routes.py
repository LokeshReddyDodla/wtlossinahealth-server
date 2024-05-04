from fastapi import FastAPI

from rest_server.meals import analyse_meal
from rest_server.system_management import reload_cache


def import_routes(app: FastAPI) -> None:
    """
    Import routes from different modules and add them to the main application
    """
    
    ###########################################################################
    # System management
    ###########################################################################
    app.include_router(reload_cache.router)

    ###########################################################################
    # Meals
    ###########################################################################
    app.include_router(analyse_meal.router)
    