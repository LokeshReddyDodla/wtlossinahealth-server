from punq import Container
from sqlalchemy.ext.asyncio import AsyncSession

from lib.services.care_provider_service import CareProviderService
from lib.services.chat_service import ChatService
from lib.services.patient_care_provider_service import \
    PatientCareProviderService
from lib.services.patient_profile_service import PatientProfileService

# Create the DI container
container = Container()

# Register services that don't require parameters (singleton services)
container.register(ChatService)

# Register services that need an AsyncSession
container.register(PatientProfileService, AsyncSession)
container.register(CareProviderService, AsyncSession)
container.register(PatientCareProviderService, AsyncSession)

def get_container() -> Container:
    """Return the DI container instance."""
    return container
