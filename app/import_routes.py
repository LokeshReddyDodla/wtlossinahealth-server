from fastapi import FastAPI

from rest_server.auth import auth
from rest_server.meals import analyse_meal
from rest_server.system_management import reload_cache
from rest_server.file_upload import file_upload
from rest_server.prescriptions import analyse_prescription
from rest_server.fitness import log as fitness_log
from rest_server.report import analyse_report
from rest_server.chat import chat, context_chat
from rest_server.users import users

def import_routes(app: FastAPI) -> None:
    """
    Import routes from different modules and add them to the main application
    """
    
    ###########################################################################
    # System management
    ###########################################################################
    app.include_router(reload_cache.router)
    
    ###########################################################################
    # File Upload
    ###########################################################################
    app.include_router(file_upload.router)

    ###########################################################################
    # Meals
    ###########################################################################
    app.include_router(analyse_meal.router)
    
    ###########################################################################
    # Prescriptions
    ###########################################################################
    app.include_router(analyse_prescription.router)
    
    ###########################################################################
    # Fitness
    ###########################################################################
    app.include_router(fitness_log.router)
    
    ###########################################################################
    # Report
    ########################################################################### 
    app.include_router(analyse_report.router)
    
    ###########################################################################
    # Chat
    ########################################################################### 
    app.include_router(chat.router)
    app.include_router(context_chat.router)
    
    ###########################################################################
    # Auth
    ########################################################################### 
    app.include_router(auth.router)
    
    ###########################################################################
    # User
    ########################################################################### 
    app.include_router(users.router)
    