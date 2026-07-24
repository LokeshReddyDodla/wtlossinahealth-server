from fastapi import FastAPI


from rest_server.auth import auth
from rest_server.care_provider.router import router as care_providers_router
from rest_server.chats.router import router as chats_router
from rest_server.dump import dump
from rest_server.file_upload import file_upload
from rest_server.health import health_check
from rest_server.health_facility.router import router as health_facility_router
from rest_server.patients.router import router as patients_router
from rest_server.admin.router import router as admin_router
from rest_server.profile_update_agent.router import router as profile_update_agent_router
from rest_server.profile_agent.router import router as profile_agent_router
from rest_server.system_management import reload_cache
from rest_server.test import test
from rest_server.test.librelink_up import router as test_llu_router
from rest_server.dashboard_metrics.router import router as dashboard_metrics_router
from rest_server.v1.router import router as v1_router

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
    # Admin
    ###########################################################################
    app.include_router(admin_router)

    ###########################################################################
    # Auth
    ###########################################################################
    app.include_router(auth.router)

    ###########################################################################
    # Health Facility
    ###########################################################################
    app.include_router(health_facility_router)

    ###########################################################################
    # Care Providers
    ###########################################################################
    app.include_router(care_providers_router)

    ###########################################################################
    # Chats
    ###########################################################################
    app.include_router(chats_router)

    ###########################################################################
    # File Upload
    ###########################################################################
    app.include_router(file_upload.router)

    ###########################################################################
    # Patient
    ###########################################################################
    app.include_router(patients_router)

    ###########################################################################
    # Dashboard Metrics
    ###########################################################################
    app.include_router(dashboard_metrics_router)

    ###########################################################################
    # V1 API
    ###########################################################################
    app.include_router(v1_router)

    ###########################################################################
    # Profile Update Agent
    ###########################################################################
    app.include_router(profile_update_agent_router)

    ###########################################################################
    # Profile Agent (unified replacement for onboarding + profile-update)
    ###########################################################################
    app.include_router(profile_agent_router)

    ###########################################################################
    # Test
    ###########################################################################
    app.include_router(test.router)
    app.include_router(test_llu_router)

    ###########################################################################
    # DUMP
    ###########################################################################
    app.include_router(dump.router)
