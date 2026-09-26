from __future__ import annotations


class TqdmDebugTaskGraph:
    class Step:
        def __len__(self):
            return 1

    class IterableStep(Step):
        def __init__(self, size: int):
            self.size = size

        def __len__(self):
            return self.size

    class Task(Step):
        steps: tuple[TqdmDebugTaskGraph.Step, ...]
        steps_size: int

        def __init__(self, size: int, *steps: TqdmDebugTaskGraph.Step):
            self.size = size
            self.steps = steps
            self.steps_size = sum([len(s) for s in steps]) or 1

        def __len__(self):
            return self.size

    steps: tuple[Step, ...]

    def __init__(self, *steps: Step):
        self.steps = steps

    def __len__(self):
        return sum([len(s) for s in self.steps])
