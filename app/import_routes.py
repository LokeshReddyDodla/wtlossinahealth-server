from fastapi import FastAPI

from rest_server.auth import auth
from rest_server.patients.cgm.router import router as cgm_router
from rest_server.patients.connected_apps.router import (
    router as connected_apps_router,
)
from rest_server.patients.fitness.router import router as fitness_router
from rest_server.patients.meals.router import router as meals_router
from rest_server.patients.permissions.router import (
    router as permissions_router,
)
from rest_server.patients.prescriptions.router import (
    router as prescriptions_router,
)
from rest_server.patients.profile.router import router as profile_router
from rest_server.patients.smbgs.router import router as smbgs_router
from rest_server.patients.vitals.router import router as vitals_router


from rest_server.system_management import reload_cache
from rest_server.file_upload import file_upload
from rest_server.chat import chat, context_chat

from rest_server.health import health_check
from rest_server.test import test
from rest_server.admin import admin
from rest_server.admin.patients import connected_apps as admin_patients
from rest_server.admin.patients.cgm import upload as admin_cgm_upload

from rest_server.health_facility.router import router as health_facility_router

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
    app.include_router(profile_router)
    app.include_router(permissions_router)
    app.include_router(vitals_router)
    app.include_router(smbgs_router)
    app.include_router(connected_apps_router)
    app.include_router(cgm_router)
    app.include_router(fitness_router)
    app.include_router(prescriptions_router)
    app.include_router(meals_router)

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

    ###########################################################################
    # Health Facility
    ###########################################################################
    app.include_router(health_facility_router)
