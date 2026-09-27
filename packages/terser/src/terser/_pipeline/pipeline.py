from abc import ABC, abstractmethod
from typing import final


class PipelineContext(ABC):
    pass


class Pipeline[C: PipelineContext](ABC):
    def __init__(self, ctx: C, /):
        self.__ctx = ctx

    @final
    @property
    def _ctx(self) -> C:
        return self.__ctx


class PipelineStep[C: PipelineContext](ABC):
    def __init__(self, pipeline: Pipeline[C], ctx: C, /):
        self.__ctx = ctx
        self.__pipeline = pipeline

    @abstractmethod
    async def __call__(self, /) -> None:
        ...

    @final
    @property
    def _ctx(self) -> C:
        return self.__ctx

    @final
    @property
    def _pipeline(self) -> Pipeline:
        return self.__pipeline


class SingleFilePipeline(Pipeline):
    pass
