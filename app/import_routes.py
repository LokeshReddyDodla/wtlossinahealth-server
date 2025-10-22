from fastapi import FastAPI


from rest_server.ai_conversations.router import (
    router as ai_conversations_router,
)
from rest_server.ai.router import router as ai_router
from rest_server.auth import auth
from rest_server.care_provider.router import router as care_providers_router
from rest_server.chats.router import router as chats_router
from rest_server.dump import dump
from rest_server.file_upload import file_upload
from rest_server.health import health_check
from rest_server.health_facility.router import router as health_facility_router
from rest_server.patients.router import router as patients_router
from rest_server.admin.router import router as admin_router
from rest_server.weight_loss_agent.router import router as weight_loss_agent_router
from rest_server.system_management import reload_cache
from rest_server.test import test


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
    # Ai Conversation
    ###########################################################################
    app.include_router(ai_conversations_router)
    app.include_router(ai_router)

    ###########################################################################
    # File Upload
    ###########################################################################
    app.include_router(file_upload.router)

    ###########################################################################
    # Patient
    ###########################################################################
    app.include_router(patients_router)

    ###########################################################################
    # Weight Loss Agent
    ###########################################################################
    # The weight loss agent router already declares its own prefix and tags.
    # Including with an additional prefix would double it (e.g., /weight-loss-agent/weight-loss-agent).
    app.include_router(weight_loss_agent_router)

    ###########################################################################
    # Test
    ###########################################################################
    app.include_router(test.router)

    ###########################################################################
    # DUMP
    ###########################################################################
    app.include_router(dump.router)
