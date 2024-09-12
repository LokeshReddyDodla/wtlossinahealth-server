from enum import Enum


class CareProviderRole(Enum):
    DOCTOR = "doctor"
    DIETITIAN = "dietitian"
    NURSE = "nurse"
    DIABETIC_EDUCATOR = "diabetic_educator"
    FITNESS_COACH = "fitness_coach"
    RESEARCH_COORDINATOR = "research_coordinator"
    ADMIN = "admin"
    LAB_TECHNICIAN = "lab_technician"


class CareProviderFeature(Enum):
    MEALS = "meals"
    REPORTS = "reports"
    FITNESS = "fitness"
    CGM = "cgm"
    CARE_PROVIDER = "care_provider"


class CareProviderPermission:
    def __init__(self, read=False, create=False, update=False, delete=False):
        self.read = read
        self.create = create
        self.update = update
        self.delete = delete

    def to_dict(self):
        return {
            "read": self.read,
            "create": self.create,
            "update": self.update,
            "delete": self.delete,
        }


CARE_PROVIDER_PERMISSIONS = {
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
        CareProviderFeature.CGM: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.CARE_PROVIDER: CareProviderPermission(
            read=True, create=False, update=True, delete=False
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
        CareProviderFeature.CGM: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.CARE_PROVIDER: CareProviderPermission(
            read=True, create=False, update=False, delete=False
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
        CareProviderFeature.CGM: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
        CareProviderFeature.CARE_PROVIDER: CareProviderPermission(
            read=True, create=False, update=False, delete=False
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
        CareProviderFeature.CGM: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.CARE_PROVIDER: CareProviderPermission(
            read=True, create=False, update=False, delete=False
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
        CareProviderFeature.CGM: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
        CareProviderFeature.CARE_PROVIDER: CareProviderPermission(
            read=True, create=False, update=False, delete=False
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
        CareProviderFeature.CGM: CareProviderPermission(
            read=True, create=True, update=False, delete=False
        ),
        CareProviderFeature.CARE_PROVIDER: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
    },
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
        CareProviderFeature.CGM: CareProviderPermission(
            read=True, create=True, update=True, delete=True
        ),
        CareProviderFeature.CARE_PROVIDER: CareProviderPermission(
            read=True, create=True, update=True, delete=True
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
        CareProviderFeature.CGM: CareProviderPermission(
            read=True, create=True, update=True, delete=False
        ),
        CareProviderFeature.CARE_PROVIDER: CareProviderPermission(
            read=True, create=False, update=False, delete=False
        ),
    },
}


# Utility function to get permissions for a specific role
def get_care_provider_permissions(role: CareProviderRole):
    return {
        feature.value: perm.to_dict()
        for feature, perm in CARE_PROVIDER_PERMISSIONS.get(role, {}).items()
    }
