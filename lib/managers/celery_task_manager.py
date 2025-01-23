from celery import Celery


class CeleryTaskManager:
    def __init__(self, app: Celery):
        self.app = app

    def is_task_in_queue_or_running(self, task_id: str) -> bool:
        """
        Check if a task with the given task_id is already queued or running.
        """
        inspect = self.app.control.inspect()
        try:
            # Check active tasks
            active_tasks = inspect.active() or {}
            for worker, tasks in active_tasks.items():
                if any(task["id"] == task_id for task in tasks):
                    return True

            # Check scheduled tasks
            scheduled_tasks = inspect.scheduled() or {}
            for worker, tasks in scheduled_tasks.items():
                if any(task["request"]["id"] == task_id for task in tasks):
                    return True

            # Check reserved tasks
            reserved_tasks = inspect.reserved() or {}
            for worker, tasks in reserved_tasks.items():
                if any(task["id"] == task_id for task in tasks):
                    return True

        except Exception as e:
            print(f"⚠️ Error while checking Celery tasks: {e}")

        return False

    def trigger_task_once(
        self, task_name: str, args: list, task_id: str, **kwargs
    ):
        """
        Trigger a task only if it's not already in the queue or running.
        """
        if not self.is_task_in_queue_or_running(task_id):
            self.app.send_task(task_name, args=args, task_id=task_id, **kwargs)
            print(f"🚀 Task '{task_name}' triggered with ID: {task_id}")
        else:
            print(
                f"⚠️ Task '{task_name}' with ID '{task_id}' is already in queue or running."
            )
