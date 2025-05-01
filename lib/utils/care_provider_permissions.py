from enum import Enum


class CareProviderPermissionAction(Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class CareProviderRole(Enum):
    DOCTOR = "doctor"
    DIETITIAN = "dietitian"
    NURSE = "nurse"
    DIABETIC_EDUCATOR = "diabetic_educator"
    FITNESS_COACH = "fitness_coach"
    RESEARCH_COORDINATOR = "research_coordinator"
    ADMIN = "admin"
    LAB_TECHNICIAN = "lab_technician" 
    # TODO: ADD Physio


class CareProviderFeature(Enum):
    MEALS = "meals"
    REPORTS = "reports"
    FITNESS = "fitness"
    CGMS = "cgms"
    CARE_PROVIDERS = "care_providers"
    HEALTH_FACILITY = "health_facility"
    PATIENTS = "patients"
    PACKAGES = "packages"
    AI_CHATS = "ai_chats"


class CareProviderPermission:
    def __init__(self, **kwargs):
        self.permissions = {
            action: kwargs.get(action.value, False)
            for action in CareProviderPermissionAction
        }

    def to_dict(self):
        return {
            action.value: self.permissions[action]
            for action in CareProviderPermissionAction
        }

    def has_permission(self, action: CareProviderPermissionAction) -> bool:
        return self.permissions.get(action, False)


CARE_PROVIDER_PERMISSIONS = {
    CareProviderRole.ADMIN: {
        CareProviderFeature.MEALS: CareProviderPermission(
            read=True, create=True, update=True, delete=True
        ),
        CareProviderFeature.REPORTS: CareProviderPermission(
            read=True, create=True, update=True, delete=True
        ),
        CareProviderFeature.FITNESS: CareProviderPermission(
            read=True, create=True, update=True, delete=True
        ),
        CareProviderFeature.CGMS: CareProviderPermission(
            read=True, create=True, update=True, delete=True
        ),
        CareProviderFeature.CARE_PROVIDERS: CareProviderPermission(
            read=True, create=True, update=True, delete=True
        ),
        CareProviderFeature.HEALTH_FACILITY: CareProviderPermission(
            read=True, create=False, update=True, delete=False
        ),
        CareProviderFeature.PATIENTS: CareProviderPermission(
            read=True, create=True, update=True, delete=True
        ),
        CareProviderFeature.PACKAGES: CareProviderPermission(
            read=True, create=True, update=True, delete=True
        ),
        CareProviderFeature.AI_CHATS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
    },
    CareProviderRole.DOCTOR: {
        CareProviderFeature.MEALS: CareProviderPermission(
            read=True, create=False, update=True, delete=False
        ),
        CareProviderFeature.REPORTS: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.FITNESS: CareProviderPermission(
            read=True, create=False, update=True, delete=False
        ),
        CareProviderFeature.CGMS: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.CARE_PROVIDERS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.HEALTH_FACILITY: CareProviderPermission(
            read=True, create=False, update=True, delete=False
        ),
        CareProviderFeature.PATIENTS: CareProviderPermission(
            read=True, create=True, update=True, delete=True
        ),
        CareProviderFeature.PACKAGES: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.AI_CHATS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
    },
    CareProviderRole.DIETITIAN: {
        CareProviderFeature.MEALS: CareProviderPermission(
            read=True, create=True, update=True, delete=True
        ),
        CareProviderFeature.REPORTS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.FITNESS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.CGMS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.CARE_PROVIDERS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.HEALTH_FACILITY: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PATIENTS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PACKAGES: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.AI_CHATS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
    },
    CareProviderRole.NURSE: {
        CareProviderFeature.MEALS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.REPORTS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
        CareProviderFeature.FITNESS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.CGMS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
        CareProviderFeature.CARE_PROVIDERS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.HEALTH_FACILITY: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PATIENTS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PACKAGES: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.AI_CHATS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
    },
    CareProviderRole.DIABETIC_EDUCATOR: {
        CareProviderFeature.MEALS: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.REPORTS: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.FITNESS: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.CGMS: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.CARE_PROVIDERS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.HEALTH_FACILITY: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PATIENTS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PACKAGES: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.AI_CHATS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
    },
    CareProviderRole.FITNESS_COACH: {
        CareProviderFeature.MEALS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.REPORTS: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.FITNESS: CareProviderPermission(
            read=True, create=True, update=True, delete=True
        ),
        CareProviderFeature.CGMS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.CARE_PROVIDERS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.HEALTH_FACILITY: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PATIENTS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PACKAGES: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.AI_CHATS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
    },
    CareProviderRole.RESEARCH_COORDINATOR: {
        CareProviderFeature.MEALS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.REPORTS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
        CareProviderFeature.FITNESS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.CGMS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
        CareProviderFeature.CARE_PROVIDERS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.HEALTH_FACILITY: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PATIENTS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PACKAGES: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.AI_CHATS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
    },
    CareProviderRole.LAB_TECHNICIAN: {
        CareProviderFeature.MEALS: CareProviderPermission(
            read=False, create=False, update=False, delete=False
        ),
        CareProviderFeature.REPORTS: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.FITNESS: CareProviderPermission(
            read=False, create=False, update=False, delete=False
        ),
        CareProviderFeature.CGMS: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.CARE_PROVIDERS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.HEALTH_FACILITY: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PATIENTS: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.PACKAGES: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.AI_CHATS: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
    },
}


# Utility function to get permissions for a specific role
def get_care_provider_permissions(role: CareProviderRole):
    return {
        feature.value: perm.to_dict()
        for feature, perm in CARE_PROVIDER_PERMISSIONS.get(role, {}).items()
    }


# Utility function to check if a specific role has permission for an action
def has_care_provider_permission(
    role: CareProviderRole,
    feature: CareProviderFeature,
    action: CareProviderPermissionAction,
) -> bool:
    feature_permissions = CARE_PROVIDER_PERMISSIONS.get(role, {}).get(feature)
    if not feature_permissions:
        return False
    return feature_permissions.has_permission(action)
