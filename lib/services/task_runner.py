import pickle
from lib.core.celery_app import celery
from lib.tasks.generic import run_function


class TaskRunner:
    def __init__(self):
        self.celery = celery

    def run_in_background(self, func, *args, **kwargs):
        # Serialize the function using pickle
        func_pickle = pickle.dumps(func)
        # Delay the task execution
        task = run_function.delay(func_pickle, *args, **kwargs)
        return task.id

    def check_task_status(self, task_id):
        result = run_function.AsyncResult(task_id)
        return result.status, result.result
