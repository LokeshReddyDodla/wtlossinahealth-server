from .tasks import generate_patient_brief

__all__ = ["generate_patient_brief", "get_tasks"]


def get_tasks():
    return [generate_patient_brief]
