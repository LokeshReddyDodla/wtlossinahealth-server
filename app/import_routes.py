from fastapi import FastAPI

from rest_server.auth import auth
from rest_server.patients.cgm import routes as cgm_routes
from rest_server.patients.connected_apps import routes as connected_apps_routes
from rest_server.patients.fitness import routes as fitness_routes
from rest_server.patients.meals import routes as meals_routes
from rest_server.patients.permissions import routes as permissions_routes
from rest_server.patients.prescriptions import routes as prescriptions_routes
from rest_server.patients.profile import routes as profile_routes
from rest_server.patients.smbgs import routes as smbgs_routes
from rest_server.patients.vitals import routes as vitals_routes


from rest_server.system_management import reload_cache
from rest_server.file_upload import file_upload
from rest_server.chat import chat, context_chat

from rest_server.health import health_check
from rest_server.test import test
from rest_server.admin import admin
from rest_server.admin.patients import connected_apps as admin_patients
from rest_server.admin.patients.cgm import upload as admin_cgm_upload

from rest_server.dump import dump


def import_routes(app: FastAPI) -> None:
    """
    Import routes from different modules and add them to the main application
    """

    ###########################################################################
    # Health
    ###########################################################################
    app.include_router(health_check.router)

    ###########################################################################
    # System management
    ###########################################################################
    app.include_router(reload_cache.router)

    ###########################################################################
    # File Upload
    ###########################################################################
    app.include_router(file_upload.router)

    ###########################################################################
    # Report
    ###########################################################################

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
    # Patient
    ###########################################################################
    app.include_router(profile_routes.router)
    app.include_router(permissions_routes.router)
    app.include_router(vitals_routes.router)
    app.include_router(smbgs_routes.router)
    app.include_router(connected_apps_routes.router)
    app.include_router(cgm_routes.router)
    app.include_router(fitness_routes.router)
    app.include_router(prescriptions_routes.router)
    app.include_router(meals_routes.router)

    ###########################################################################
    # Test
    ###########################################################################
    app.include_router(test.router)

    ###########################################################################
    # DUMP
    ###########################################################################
    app.include_router(dump.router)

    ###########################################################################
    # Admin
    ###########################################################################
    app.include_router(admin.router)
    app.include_router(admin_patients.router)
    app.include_router(admin_cgm_upload.router)
