from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WorkflowError(Exception):
    code: str
    user_message: str
    technical_message: str = ""
    retryable: bool = False
    requires_cookies: bool = False

    def __str__(self) -> str:
        return self.technical_message or self.user_message


class TaskCanceled(WorkflowError):
    def __init__(self) -> None:
        super().__init__("TASK_CANCELED", "تم إلغاء المهمة", retryable=False)
