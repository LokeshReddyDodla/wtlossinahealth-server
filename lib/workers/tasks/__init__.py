"""Task registry - aggregates all tasks for ARQ worker."""

from typing import Callable, List

from loguru import logger


def get_all_tasks() -> List[Callable]:
    tasks = []
    
    from lib.workers.tasks.cgm import get_tasks as get_cgm_tasks
    from lib.workers.tasks.device import get_tasks as get_device_tasks
    from lib.workers.tasks.fcm import get_tasks as get_fcm_tasks
    from lib.workers.tasks.fitness import get_tasks as get_fitness_tasks
    from lib.workers.tasks.libreview import get_tasks as get_libreview_tasks
    from lib.workers.tasks.meal import get_tasks as get_meal_tasks
    from lib.workers.tasks.package import get_tasks as get_package_tasks
    from lib.workers.tasks.patient_summary import get_tasks as get_patient_summary_tasks
    from lib.workers.tasks.patient_export import get_tasks as get_patient_export_tasks
    from lib.workers.tasks.profile import get_tasks as get_profile_tasks
    from lib.workers.tasks.sleep import get_tasks as get_sleep_tasks
    from lib.workers.tasks.smbg import get_tasks as get_smbg_tasks
    from lib.workers.tasks.vitals import get_tasks as get_vitals_tasks
    from lib.workers.tasks.weightloss_agent_tasks import get_tasks as get_weightloss_agent_tasks
    
    tasks.extend(get_cgm_tasks())
    tasks.extend(get_device_tasks())
    tasks.extend(get_fcm_tasks())
    tasks.extend(get_fitness_tasks())
    tasks.extend(get_libreview_tasks())
    tasks.extend(get_meal_tasks())
    tasks.extend(get_package_tasks())
    tasks.extend(get_patient_summary_tasks())
    tasks.extend(get_patient_export_tasks())
    tasks.extend(get_profile_tasks())
    tasks.extend(get_sleep_tasks())
    tasks.extend(get_smbg_tasks())
    tasks.extend(get_vitals_tasks())
    tasks.extend(get_weightloss_agent_tasks())
    
    logger.info(f"Registered {len(tasks)} ARQ tasks")
    return tasks


__all__ = ["get_all_tasks"]
