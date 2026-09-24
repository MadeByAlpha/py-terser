import argparse
import typing
from dataclasses import is_dataclass
from enum import EnumType
from types import UnionType
from typing import TYPE_CHECKING, Any, Annotated, get_args, get_origin, override

from alpha93.commons.pydantic import dataclasses
from pydantic import BaseModel

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

    type ArgParse = argparse._ActionsContainer


if TYPE_CHECKING:
    type MutuallyExclusive[T] = Annotated[T, ...]
else:
    class MutuallyExclusive:
        def __class_getitem__(cls, item: Any) -> Any:
            return Annotated[item, cls()]

        @override
        def __hash__(self) -> int:
            return hash(type(self))

UnionConstructor: Any = UnionType
LiteralGenericAlias = getattr(typing, "_LiteralGenericAlias")


class _ModelArgumentBuilder:
    __LOCK = object()

    def __init__(self, lock: object, parser: argparse.ArgumentParser):
        if lock is not _ModelArgumentBuilder.__LOCK:
            raise RuntimeError("Lock object does not match")

        self.parser = parser

    @staticmethod
    def from_model(parser: argparse.ArgumentParser, model: type[BaseModel]):
        _ModelArgumentBuilder(_ModelArgumentBuilder.__LOCK, parser).__iter_fields(parser, model)

    def __iter_fields(self, args: ArgParse, model: type[BaseModel]):
        if is_dataclass(model):
            model = dataclasses.to_model(model) # type: ignore[invalid-type]

        model_fields: dict[str, FieldInfo] = model.model_fields
        for field, field_info in model_fields.items():
            annotation: type[BaseModel] = field_info.annotation # type: ignore[invalid-type]
            if any(isinstance(m, MutuallyExclusive) for m in field_info.metadata):
                if BaseModel not in annotation.mro() and not is_dataclass(annotation):
                    raise ValueError

                # the group itself is optional: leaving out every option of it means "use the defaults"
                group = self.parser.add_mutually_exclusive_group(required=False)
                self.__iter_fields(group, annotation)   # type: ignore[invalid-type]
                continue

            types: list[Any] = [annotation]
            if isinstance(annotation, UnionType):
                types = list(get_args(annotation))

            models = set(filter(lambda x: isinstance(x, type(BaseModel)) or is_dataclass(x), types))
            if not len(models):
                self.__add_arg(args, field, field_info, annotation) # type: ignore[invalid-type]
                continue

            group = self.parser.add_argument_group(
                title=field,
                description=field_info.description,
                argument_default=field_info.default,
            )

            if len(type_params := set(types) - models):
                annotation = UnionConstructor[tuple(type_params)]
                self.__add_arg(group, field, field_info, annotation) # type: ignore[invalid-type]

            for type_param in models:
                self.__iter_fields(group, type_param)       # type: ignore[invalid-type]

    def __add_arg(self, parser: ArgParse, field: str, field_info: FieldInfo, model: type):
        if isinstance(model, type(BaseModel)) or is_dataclass(model):
            self.__iter_fields(parser, model)   # type: ignore[invalid-type]
            return

        if isinstance(model, UnionType):
            non_none = [t for t in get_args(model) if t is not type(None)]
            model = non_none[0] if len(non_none) == 1 else None

        choices, metavar = None, None
        action, nargs, const = "store", None, None
        if model is bool:
            # `--flag`, `--flag True` and `--flag False` all work
            choices, metavar, nargs, const = [True, False], "{True,False}", '?', True
            model = str_to_bool
        elif isinstance(model, LiteralGenericAlias):
            choices = get_args(model)
            model = type(choices[0])
        elif isinstance(model, EnumType):
            choices = list(model.__members__)
            if not len(choices):
                choices = None

        if get_origin(model) in (list, set, frozenset, tuple):
            # 'extend' (not 'append') so repeated uses of the flag accumulate into a
            # flat list matching the field's collection type, instead of a list of lists.
            action, nargs = "extend", '+'
            # argparse's `type=` converts each individual token, so it needs the
            # collection's element type (e.g. `str`), not the collection type itself
            # (calling `set[str]("foo")` would build a set of its characters).
            elem_types = get_args(model)
            model = elem_types[0] if elem_types else str

        # an `extend` default would be extended rather than replaced, so collections start out as
        # None and fall back to the field's default when the option isn't given
        default = None if action == "extend" else field_info.get_default(call_default_factory=True)
        kwargs = {"const": const} if const is not None else {}
        parser.add_argument(
            "--" + field.replace('_', '-'),
            action=action,
            nargs=nargs,
            default=default,
            metavar=metavar,
            type=model, # type: ignore[invalid-type]
            choices=choices,
            required=field_info.is_required(),
            help=field_info.description,
            dest=field,
            deprecated=field_info.deprecated,
            **kwargs,
        )

_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})


def str_to_bool(value: str) -> bool:
    match value.strip().lower():
        case v if v in _TRUE:
            return True
        case v if v in _FALSE:
            return False
    raise argparse.ArgumentTypeError(f"expected True or False, got {value!r}")


def normalize_bool_flags(parser: argparse.ArgumentParser, argv: list[str]) -> list[str]:
    """
    Give every bare boolean flag an explicit `True`, so a flag directly followed by a positional
    argument (`--in-place src/`) doesn't take that argument as its value.
    """

    flags = {
        option
        for action in parser._actions if action.type is str_to_bool
        for option in action.option_strings
    }

    normalized: list[str] = []
    for i, arg in enumerate(argv):
        normalized.append(arg)
        if arg == "--":
            normalized.extend(argv[i + 1:])
            break

        if arg in flags and (i + 1 == len(argv) or argv[i + 1].strip().lower() not in _TRUE | _FALSE):
            normalized.append("True")

    return normalized


arguments_from_model = _ModelArgumentBuilder.from_model
