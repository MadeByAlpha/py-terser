from typing import final, override

from .abc import StepContext
from .reporter import BaseReporter
from .tasks import Task, TaskProvider


@final
class HeadlessReporter(BaseReporter):
    @override
    def _step_context(self, message: str, /):
        return _EmptyStepContext()

    @override
    def _task_provider(self, message: str, /):
        return _EmptyTaskProvider()

    @override
    def init(self, /, **kwargs) -> None:
        pass

    @override
    def prepare(self, message: str):
        return self._base_step(message)

    @override
    def close(self):
        pass


@final
class _EmptyStepContext(StepContext):
    @override
    def __enter__(self) -> None:
        pass

    @override
    def __next__(self) -> None:
        pass

    @override
    def _exit(self, *args, **kwargs) -> None:
        pass


@final
class EmptyTask(Task):
    """A task that reports nothing, for running a pipeline step outside any reporter."""

    @override
    def _step_context(self, message: str, /):
        return _EmptyStepContext()

    @override
    def done(self, /) -> None:
        pass


@final
class _EmptyTaskProvider(TaskProvider):
    @override
    def __enter__(self) -> None:
        pass

    @override
    def _exit(self, *args, **kwargs):
        pass

    @override
    def _task(self):
        # noinspection argument-list
        return EmptyTask()
