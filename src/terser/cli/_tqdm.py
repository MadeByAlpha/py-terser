from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock
from typing import override

from tqdm import tqdm

from alpha93.progression import BaseReporter, StepContext, Task, TaskProvider
from alpha93.progression.abc import BaseStep
from terser.utils.cli_helper import TqdmDebugTaskGraph


class _StateHolder(ABC):
    @abstractmethod
    def set_status(self, status: str):
        ...

    @abstractmethod
    def update(self, n: int, /):
        ...

    @abstractmethod
    def end_status(self, /):
        ...


class _Context[T: TqdmDebugTaskGraph.Step]:
    def __init__(self, reporter: _StateHolder, tg: T, /):
        self.__ctx = reporter
        self._tg = tg

        self._cur = 0

    def enter(self, message: str):
        self.__ctx.set_status(message)

    def next(self):
        self._cur += 1
        self.__ctx.update(1)

    def close(self):
        self.__ctx.end_status()
        if (len(self._tg) <= 1) or (len(self._tg) - self._cur <= 1):
            return
        self.__ctx.update(len(self._tg) - self._cur - 1)


class _TaskContext(_Context[TqdmDebugTaskGraph.Task]):
    def __init__(self, reporter: _TqdmTaskProvider, context: _Context, /):
        self.__holder = reporter
        super().__init__(reporter, context._tg)

    def close(self):
        self.__holder.update(1)
        self.__holder.close_task()


class _TqdmPrepareStepContext(StepContext):
    def __init__(self, reporter: _StateHolder, message: str, /):
        self.__ctx = reporter
        self.__msg = message
        self.__lock = False

    def __enter__(self):
        self.__ctx.set_status(self.__msg)

    def __next__(self):
        if self.__lock:
            raise NotImplementedError
        self.__lock = True

    def _exit(self, *__, **_) -> None:
        pass


class _TqdmStepContext(StepContext):
    def __init__(self, context: _Context, message: str, /):
        self.__ctx = context
        self.__msg = message

    def __enter__(self):
        self.__ctx.enter(message=self.__msg)

    def __next__(self):
        self.__ctx.next()

    def _exit(self, *__, **_) -> None:
        self.__ctx.close()


class _TqdmTask(Task):
    def __init__(self, pv: _TqdmTaskProvider, i: int, context: _TaskContext, /):
        self.__pv = pv
        self.__id = i
        self.__ctx = context
        self.__cur = 0

    def _step_context(self, message: str, /) -> StepContext:
        phase, self.__cur = self.__ctx._tg.steps[self.__cur], self.__cur + 1
        return _TqdmStepContext(_Context(self.__pv, phase), message)

    def done(self, /) -> None:
        self.__ctx.close()


class _TqdmTaskProvider(TaskProvider, _StateHolder):
    def set_status(self, status: str):
        pass

    def update(self, n: int, /):
        with self.__parent.get_lock():
            with self.__lock:
                self.__bar.n += n
            self.__parent.display(pos=0)
            self.__bar.display(pos=1)

    def end_status(self, /):
        pass

    def close_task(self, /):
        self.__ctx.next()

    def __init__(self, context: _Context[TqdmDebugTaskGraph.Task], parent: tqdm, message: str, bars: list[tqdm], /):
        self.__ctx = context
        self.__msg = message
        self.__cur = 0

        self.__parent = parent
        self.__lock = Lock()
        self.__bars = bars

    def __enter__(self) -> None:
        self.__bar: tqdm = tqdm(total=len(self.__ctx._tg) * self.__ctx._tg.steps_size, leave=False)
        self.__bars.append(self.__bar)
        self.__ctx.enter(self.__msg)

    # noinspection argument-list,bad-return
    def _task(self) -> Task:
        task, self.__cur = _TqdmTask(self, self.__cur, _TaskContext(self, self.__ctx)), self.__cur + 1
        return task

    def _exit(self, *__, **_) -> None:
        self.__bar.clear()
        self.__bar.close()
        self.__ctx._cur = self.__cur
        self.__ctx.close()


class TqdmReporter(BaseReporter, _StateHolder):
    __tg: TqdmDebugTaskGraph
    __bar: tqdm

    __phase: int
    __step: TqdmDebugTaskGraph.Step | None

    def __init__(self):
        self.__bar: tqdm = tqdm()
        self.__phase = 0
        # every bar this reporter created, closed together in `close()` - a bar left open is only
        # closed by its finalizer, which fails noisily during interpreter shutdown
        self.__bars: list[tqdm] = [self.__bar]

    def set_status(self, status: str):
        self.__bar.set_description_str(status)

    def update(self, n: int, /):
        with self.__bar.get_lock():
            self.__bar.update(n)

    def end_status(self, /):
        assert self.__step is not None
        del self.__step
        self.__step = None
        self.__bar.display('', pos=1)
        self.__bar.display(pos=0)

    @override
    def prepare(self, message: str):
        return BaseStep(_TqdmPrepareStepContext(self, message))

    @override
    def init(self, /, **kwargs):
        self.__tg: TqdmDebugTaskGraph = kwargs["task_graph"]
        self.__bar.total = len(self.__tg)
        self.__bar.reset(len(self.__tg))
        self.__step = None

    @override
    def _step_context(self, message: str, /) -> StepContext:
        phase, self.__phase = self.__tg.steps[self.__phase], self.__phase + 1
        if isinstance(phase, TqdmDebugTaskGraph.Task):
            raise TypeError(f"Expected a Step graph, got {phase.__class__.__name__}")

        assert self.__step is None
        self.__step = phase
        return _TqdmStepContext(_Context(self, phase), message)

    @override
    def _task_provider(self, message: str, /) -> TaskProvider:
        phase, self.__phase = self.__tg.steps[self.__phase], self.__phase + 1
        if not isinstance(phase, TqdmDebugTaskGraph.Task):
            raise TypeError(f"Expected a SubTask graph, got {phase.__class__.__name__}")

        assert self.__step is None
        self.__step = phase
        return _TqdmTaskProvider(_Context(self, phase), self.__bar, message, self.__bars)

    @override
    def close(self):
        self.update(1)
        self.__bar.display('', pos=1)
        self.__bar.display(pos=0)

        for bar in reversed(self.__bars):
            bar.close()
