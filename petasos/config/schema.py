"""Declarative config sections.

One declaration drives validation, mapping, and the description a settings
form needs. Constructing a section and reading one from a mapping apply the
same checks and report every problem together.
"""

from __future__ import annotations

import difflib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import MISSING, dataclass, field, fields, replace
from types import MappingProxyType, NoneType, UnionType
from typing import (
    Any,
    Literal,
    TypeVar,
    Union,
    cast,
    dataclass_transform,
    get_args,
    get_origin,
    get_type_hints,
)

_T = TypeVar("_T")
_S = TypeVar("_S")

Audience = Literal["basic", "advanced", "expert"]
_TYPE_NAMES = {
    "bool": "bool",
    "int": "int",
    "float": "float",
    "str": "str",
    "choice": "choice",
    "strings": "tuple[str, ...]",
    "map_float": "mapping[str, float]",
    "map_str": "mapping[str, str]",
}
_MISSING = object()


class ConfigError(ValueError):
    """Every problem found while reading one config document."""

    errors: tuple[tuple[str, str], ...]

    def __init__(self, problems: str | Sequence[tuple[str, str]], /) -> None:
        self.errors = _problems(problems)
        super().__init__(_format(self.errors))

    @classmethod
    def at(cls, path: str, message: str) -> ConfigError:
        """Report one problem at a path relative to the section being checked."""
        if path == "" or path.startswith("."):
            raise TypeError("path must name a setting relative to this section")
        if message == "":
            raise TypeError("message must be a non-empty string")
        return cls(((path, message),))


def _problems(problems: str | Sequence[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    if isinstance(problems, str):
        if problems == "":
            raise TypeError("ConfigError needs a message")
        return (("", problems),)
    pairs = tuple((path, message) for path, message in problems)
    if not pairs:
        raise TypeError("ConfigError needs at least one problem")
    return pairs


def _format(errors: Sequence[tuple[str, str]]) -> str:
    lines = [f"{path}: {message}" if path else message for path, message in errors]
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """The constraints declared for one setting.

    Stored on the dataclass field under the ``FieldSpec`` metadata key.
    Bounds on a mapping apply to each value. ``normalize`` runs on each item
    of a text list after the item is trimmed.
    """

    help: str
    ge: float | None = None
    gt: float | None = None
    le: float | None = None
    lt: float | None = None
    restart: bool = False
    audience: Audience = "advanced"
    normalize: Callable[[str], str] | None = None


@dataclass(frozen=True, slots=True)
class FieldInfo:
    """One leaf setting, enough to render a form and a reference row.

    ``type_name`` is ``bool``, ``int``, ``float``, ``str``, ``choice``,
    ``tuple[str, ...]``, ``mapping[str, float]``, or ``mapping[str, str]``.
    ``choices`` is set for a choice and is otherwise None. ``default`` is
    JSON-serialisable: a list for text items, a dict for a mapping. Bounds on
    a mapping apply to each value.
    """

    path: str
    type_name: str
    default: Any
    choices: tuple[Any, ...] | None
    ge: float | None
    gt: float | None
    le: float | None
    lt: float | None
    help: str
    audience: Audience
    restart: bool
    nullable: bool


@dataclass(frozen=True, slots=True)
class SectionInfo:
    """One nested section, emitted immediately before that section's own rows.

    ``path`` is the dotted path of the section field. ``help`` is the text
    declared with ``setting`` on that field. A direct child is a row whose
    path is ``path`` plus one dotted name, so the flat result is enough to
    rebuild the tree in declaration order. ``audience``, ``restart``, and
    ``nullable`` come from that same field.
    """

    path: str
    help: str
    audience: Audience
    restart: bool
    nullable: bool


@dataclass(frozen=True, slots=True)
class _Kind:
    kind: str
    nullable: bool
    choices: tuple[Any, ...]
    section: type[object] | None


@dataclass(frozen=True, slots=True)
class _Field:
    name: str
    kind: str
    nullable: bool
    choices: tuple[Any, ...]
    spec: FieldSpec
    section: type[object] | None
    default: object


def setting(
    *,
    default: _T,
    help: str,
    ge: int | float | None = None,
    gt: int | float | None = None,
    le: int | float | None = None,
    lt: int | float | None = None,
    restart: bool = False,
    audience: Audience = "advanced",
    normalize: Callable[[str], str] | None = None,
) -> _T:
    """Declare one setting's default and constraints.

    ``default`` is keyword-only so a type checker sees the constructor default.
    A list, set, or bytearray default is rejected. A dict default is copied
    into a read-only mapping, so the caller's dict is not shared.
    """
    if help.strip() == "":
        raise TypeError("setting() help must be a non-empty string")
    lower_ge = _bound("ge", ge)
    lower_gt = _bound("gt", gt)
    upper_le = _bound("le", le)
    upper_lt = _bound("lt", lt)
    _bounds_possible(lower_ge, lower_gt, upper_le, upper_lt)
    spec = FieldSpec(
        help=help,
        ge=lower_ge,
        gt=lower_gt,
        le=upper_le,
        lt=upper_lt,
        restart=restart,
        audience=audience,
        normalize=normalize,
    )
    frozen = _freeze_default(default)
    # Dataclasses reject an unhashable default. A mapping, or a section that
    # holds one, is shared through a factory; our constructor reads the plan.
    if _unhashable(frozen):
        return cast("_T", field(default_factory=_shared(frozen), metadata={FieldSpec: spec}))
    return cast("_T", field(default=frozen, metadata={FieldSpec: spec}))


def _unhashable(value: object) -> bool:
    return getattr(type(value), "__hash__", None) is None


def _shared(value: Any) -> Callable[[], Any]:
    def factory() -> Any:
        return value

    return factory


def _bound(name: str, value: object) -> float | None:
    if value is None:
        return None
    # bool is an int, and it is not a numeric bound.
    if type(value) is int:
        return float(value)
    if type(value) is float and math.isfinite(value):
        return value
    raise TypeError(f"setting() {name} must be a finite number")


def _bounds_possible(
    ge: float | None, gt: float | None, le: float | None, lt: float | None
) -> None:
    lower = gt if gt is not None else ge
    upper = lt if lt is not None else le
    if lower is None or upper is None:
        return
    exclusive = gt is not None or lt is not None
    impossible = lower >= upper if exclusive else lower > upper
    if impossible:
        raise TypeError("setting() bounds leave no valid number")


def _freeze_default(default: object) -> object:
    if isinstance(default, (list, set, bytearray)):
        raise TypeError(
            "setting() default must be immutable; "
            f"got {type(default).__name__}. Use a tuple for a list of text."
        )
    if isinstance(default, Mapping):
        return MappingProxyType(dict(default.items()))
    return default


def _require_plan(cls: type[object]) -> tuple[_Field, ...]:
    # Look up the class dict so a subclass does not inherit its parent's plan.
    plan = cls.__dict__.get("_petasos_schema")
    if not isinstance(plan, tuple):
        name = cls.__name__ if isinstance(cls, type) else str(cls)
        raise TypeError(f"{name} is not a config section")
    return cast("tuple[_Field, ...]", plan)


@dataclass_transform(frozen_default=True, kw_only_default=True, field_specifiers=(setting,))
def section(cls: type[_S]) -> type[_S]:
    """Declare a frozen config section that validates on construction.

    Direct construction and ``from_mapping`` coerce and check the same way.
    Construction takes each setting by name. ``dataclasses.replace`` builds a
    new instance, so it re-validates. A ``check`` method may raise
    ``ConfigError`` for rules that span fields; paths in that error are
    relative to the section.
    """
    if "__init__" in cls.__dict__ or "__post_init__" in cls.__dict__:
        raise TypeError(
            f"{cls.__name__} must not define __init__ or __post_init__; "
            "put cross-field rules in check()"
        )
    converted = dataclass(frozen=True, slots=True, kw_only=True)(cls)
    plan = _compile(converted)
    _store_plan(converted, plan)
    _install_init(converted)
    try:
        converted()
    except ConfigError as exc:
        raise TypeError(f"{converted.__name__} defaults are not valid ({exc})") from exc
    return converted


def _store_plan(cls: type[Any], plan: tuple[_Field, ...]) -> None:
    cls._petasos_schema = plan


def _install_init(cls: type[Any]) -> None:
    def __init__(self: object, *args: object, **kwargs: object) -> None:
        if args:
            names = ", ".join(item.name for item in _require_plan(type(self)))
            raise TypeError(f"{type(self).__name__}() takes keyword arguments only ({names})")
        _construct(self, kwargs)

    cls.__init__ = __init__


def _hints(cls: type[Any]) -> dict[str, Any]:
    # Module globals only. get_type_hints is not given the caller's locals.
    try:
        return get_type_hints(cls)
    except NameError as exc:
        raise TypeError(
            f"{cls.__name__} annotations could not be resolved ({exc}). "
            "Import the name at runtime; a TYPE_CHECKING import is not visible "
            "when the section is defined."
        ) from exc
    except (TypeError, ValueError) as exc:
        raise TypeError(f"could not resolve annotations for {cls.__name__}: {exc}") from exc


def _compile(cls: type[Any]) -> tuple[_Field, ...]:
    hints = _hints(cls)
    compiled: list[_Field] = []
    for dc_field in fields(cls):
        if dc_field.name in ("check", "_petasos_schema"):
            raise TypeError(f"{cls.__name__}.{dc_field.name} is reserved")
        spec = dc_field.metadata.get(FieldSpec)
        if not isinstance(spec, FieldSpec):
            raise TypeError(f"{cls.__name__}.{dc_field.name} must be declared with setting()")
        kind = _classify(cls, dc_field.name, hints.get(dc_field.name, dc_field.type))
        _check_kind(cls, dc_field.name, kind, spec)
        raw_default = (
            dc_field.default_factory()
            if dc_field.default_factory is not MISSING
            else dc_field.default
        )
        item = _Field(
            name=dc_field.name,
            kind=kind.kind,
            nullable=kind.nullable,
            choices=kind.choices,
            spec=spec,
            section=kind.section,
            default=raw_default,
        )
        value, errors = _convert(item, raw_default, dc_field.name)
        if errors:
            raise TypeError(f"{cls.__name__} default is not valid ({_format(errors)})")
        if _unhashable(value):
            dc_field.default = MISSING
            dc_field.default_factory = _shared(value)
        else:
            dc_field.default = value
            dc_field.default_factory = MISSING
        compiled.append(replace(item, default=value))
    return tuple(compiled)


def _classify(cls: type[object], name: str, hint: object) -> _Kind:
    inner, nullable = _unwrap(cls, name, hint)
    if inner is bool:
        return _Kind("bool", nullable, (), None)
    if inner is int:
        return _Kind("int", nullable, (), None)
    if inner is float:
        return _Kind("float", nullable, (), None)
    if inner is str:
        return _Kind("str", nullable, (), None)
    if isinstance(inner, type) and _is_section_type(inner):
        return _Kind("section", nullable, (), inner)
    origin = get_origin(inner)
    args = get_args(inner)
    if origin is Literal:
        return _Kind("choice", nullable, _choices(cls, name, args), None)
    if origin is tuple and args == (str, Ellipsis):
        return _Kind("strings", nullable, (), None)
    if origin is Mapping and args == (str, float):
        return _Kind("map_float", nullable, (), None)
    if origin is Mapping and args == (str, str):
        return _Kind("map_str", nullable, (), None)
    raise _unsupported(cls, name, inner)


def _is_section_type(cls: type[object]) -> bool:
    return isinstance(cls.__dict__.get("_petasos_schema"), tuple)


def _unwrap(cls: type[object], name: str, hint: object) -> tuple[object, bool]:
    origin = get_origin(hint)
    if origin is not Union and origin is not UnionType:
        return hint, False
    args = tuple(arg for arg in get_args(hint) if arg is not NoneType)
    nullable = len(args) != len(get_args(hint))
    if len(args) != 1:
        raise TypeError(
            f"{cls.__name__}.{name}: {_hint_name(hint)} is not a supported setting type. "
            "Combine one supported type with None."
        )
    return args[0], nullable


def _choices(cls: type[object], name: str, args: tuple[Any, ...]) -> tuple[Any, ...]:
    if not args:
        raise TypeError(f"{cls.__name__}.{name}: a choice list must not be empty")
    seen: list[object] = []
    for choice in args:
        if type(choice) not in (bool, int, float, str, NoneType) or (
            type(choice) is float and not math.isfinite(choice)
        ):
            raise TypeError(
                f"{cls.__name__}.{name}: choices must be text, numbers, true, false, or nothing"
            )
        if any(type(choice) is type(previous) and choice == previous for previous in seen):
            raise TypeError(f"{cls.__name__}.{name}: the choice {_got(choice)} is repeated")
        seen.append(choice)
    return tuple(seen)


def _unsupported(cls: type[object], name: str, hint: object) -> TypeError:
    origin = get_origin(hint)
    advice = ""
    if origin in (list, tuple):
        advice = " Use tuple[str, ...] for a list of text."
    elif origin is dict:
        advice = " Use Mapping[str, float] or Mapping[str, str]."
    elif isinstance(hint, type) and hint not in (bool, int, float, str):
        advice = " Nested groups must be decorated with @section."
    return TypeError(
        f"{cls.__name__}.{name}: {_hint_name(hint)} is not a supported setting type.{advice}"
    )


def _hint_name(hint: object) -> str:
    if isinstance(hint, type):
        return hint.__name__
    text = str(hint)
    return text.replace("typing.", "").replace("collections.abc.", "")


def _check_kind(cls: type[object], name: str, kind: _Kind, spec: FieldSpec) -> None:
    bounded = any(value is not None for value in (spec.ge, spec.gt, spec.le, spec.lt))
    if bounded and kind.kind not in ("int", "float", "map_float"):
        raise TypeError(f"{cls.__name__}.{name}: bounds apply only to numbers")
    if spec.normalize is not None and kind.kind != "strings":
        raise TypeError(f"{cls.__name__}.{name}: normalize applies only to a list of text")


def _construct(self: object, kwargs: Mapping[str, object]) -> None:
    values, errors = _convert_fields(type(self), kwargs)
    if errors:
        raise ConfigError(errors)
    for name, value in values.items():
        object.__setattr__(self, name, value)
    _run_check(self)


def _convert_fields(
    cls: type[object], provided: Mapping[str, object]
) -> tuple[dict[str, object], list[tuple[str, str]]]:
    plan = _require_plan(cls)
    known = {item.name for item in plan}
    names = [item.name for item in plan]
    errors: list[tuple[str, str]] = []
    for key in provided:
        if key not in known:
            errors.append((str(key), _unknown(str(key), names)))
    values: dict[str, object] = {}
    for item in plan:
        if item.name not in provided:
            values[item.name] = item.default
            continue
        value, field_errors = _convert(item, provided[item.name], item.name)
        if field_errors:
            errors.extend(field_errors)
        else:
            values[item.name] = value
    return values, errors


def _run_check(obj: object) -> None:
    check = getattr(obj, "check", None)
    if check is not None:
        check()


def _convert(item: _Field, value: object, path: str) -> tuple[object, tuple[tuple[str, str], ...]]:
    if value is None:
        if item.nullable:
            return None, ()
        return _bad(path, _must(item, value))
    if item.kind == "section":
        return _convert_section(item, value, path)
    if item.kind == "bool":
        if type(value) is bool:
            return value, ()
        return _bad(path, _must(item, value))
    if item.kind == "int":
        return _convert_int(item, value, path)
    if item.kind == "float":
        return _convert_float(item, value, path)
    if item.kind == "str":
        if type(value) is str:
            return value, ()
        return _bad(path, _must(item, value))
    if item.kind == "choice":
        if any(type(value) is type(choice) and value == choice for choice in item.choices):
            return value, ()
        return _bad(path, _must(item, value))
    if item.kind == "strings":
        return _convert_strings(item, value, path)
    if item.kind in ("map_float", "map_str"):
        return _convert_map(item, value, path)
    raise TypeError(f"unsupported setting kind {item.kind}")


def _bad(path: str, message: str) -> tuple[object, tuple[tuple[str, str], ...]]:
    return None, ((path, message),)


def _convert_int(
    item: _Field, value: object, path: str
) -> tuple[object, tuple[tuple[str, str], ...]]:
    # Reject bool before int: True is an int, and it is not a count.
    if type(value) is not int or not _within(value, item.spec):
        return _bad(path, _must(item, value))
    return value, ()


def _convert_float(
    item: _Field, value: object, path: str
) -> tuple[object, tuple[tuple[str, str], ...]]:
    # A whole number is accepted where a float is declared and stored as a float.
    if type(value) is int:
        number = float(value)
    elif type(value) is float:
        number = value
    else:
        return _bad(path, _must(item, value))
    if not math.isfinite(number) or not _within(number, item.spec):
        return _bad(path, _must(item, value))
    return number, ()


def _convert_strings(
    item: _Field, value: object, path: str
) -> tuple[object, tuple[tuple[str, str], ...]]:
    # A bare string would otherwise iterate into single characters.
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        return _bad(path, _must(item, value))
    errors: list[tuple[str, str]] = []
    cleaned: list[str] = []
    for index, raw in enumerate(value):
        item_path = f"{path}[{index}]"
        if type(raw) is not str:
            errors.append((item_path, f"must be text, got {_got(raw)}"))
            continue
        text = raw.strip()
        if text == "":
            errors.append((item_path, "must not be empty"))
            continue
        if item.spec.normalize is not None:
            normalized = item.spec.normalize(text)
            if type(normalized) is not str:
                raise TypeError(
                    f"normalize for {path} must return text, got {type(normalized).__name__}"
                )
            text = normalized
            if text == "":
                errors.append((item_path, "must not be empty"))
                continue
        cleaned.append(text)
    if errors:
        return None, tuple(errors)
    return tuple(cleaned), ()


def _convert_map(
    item: _Field, value: object, path: str
) -> tuple[object, tuple[tuple[str, str], ...]]:
    if not isinstance(value, Mapping):
        return _bad(path, _must(item, value))
    errors: list[tuple[str, str]] = []
    cleaned: dict[str, object] = {}
    seen: set[str] = set()
    # Value checks reuse the number or text rules. Bounds on the mapping apply
    # to each number.
    value_field = _Field(item.name, "float", False, (), item.spec, None, 0.0)
    for raw_key, raw_value in value.items():
        if type(raw_key) is not str:
            errors.append((path, f"each name must be text, got {_got(raw_key)}"))
            continue
        key = raw_key.strip()
        if key == "":
            errors.append((path, "each name must not be empty"))
            continue
        if key in seen:
            errors.append((path, f'the name "{key}" is repeated'))
            continue
        seen.add(key)
        entry = _join(path, key)
        if item.kind == "map_str":
            if type(raw_value) is not str:
                errors.append((entry, f"must be text, got {_got(raw_value)}"))
                continue
            cleaned[key] = raw_value
            continue
        number, number_errors = _convert_float(value_field, raw_value, entry)
        if number_errors:
            errors.extend(number_errors)
            continue
        cleaned[key] = number
    if errors:
        return None, tuple(errors)
    return MappingProxyType(cleaned), ()


def _convert_section(
    item: _Field, value: object, path: str
) -> tuple[object, tuple[tuple[str, str], ...]]:
    section_cls = cast("type[Any]", item.section)
    if type(value) is section_cls:
        return value, ()
    if not isinstance(value, Mapping):
        return _bad(path, _must(item, value))
    clean: dict[str, object] = {}
    errors: list[tuple[str, str]] = []
    for key, raw in value.items():
        if type(key) is not str:
            errors.append((path, f"a setting name must be text, got {_got(key)}"))
        else:
            clean[key] = raw
    try:
        built = cast("Callable[..., object]", section_cls)(**clean)
    except ConfigError as exc:
        # The nested section reported paths relative to itself.
        errors.extend((_join(path, child), message) for child, message in exc.errors)
        return None, tuple(errors)
    if errors:
        return None, tuple(errors)
    return built, ()


def _within(number: float, spec: FieldSpec) -> bool:
    lower_ok = (spec.gt is None or number > spec.gt) and (spec.ge is None or number >= spec.ge)
    upper_ok = (spec.lt is None or number < spec.lt) and (spec.le is None or number <= spec.le)
    return lower_ok and upper_ok


def _must(item: _Field, value: object) -> str:
    if item.kind == "bool":
        core = "must be true or false"
    elif item.kind == "int":
        note = " (not true or false)" if type(value) is bool else ""
        core = f"must be a whole number{_bounds(item.spec)}{note}"
    elif item.kind == "float":
        note = " (not true or false)" if type(value) is bool else ""
        core = f"must be a finite number{_bounds(item.spec)}{note}"
    elif item.kind == "str":
        core = "must be text"
    elif item.kind == "choice":
        core = f"must be exactly {_choice_text(item.choices)}"
    elif item.kind == "strings":
        if isinstance(value, str):
            core = "must be a list of text values, not a single text value"
        else:
            core = "must be a list of text values"
    elif item.kind in ("map_float", "map_str"):
        core = "must be a group of named values"
    else:
        core = "must be a group of settings"
    if item.nullable:
        core = f"{core}, or nothing"
    return f"{core}, got {_got(value)}"


def _bounds(spec: FieldSpec) -> str:
    parts: list[str] = []
    if spec.gt is not None:
        parts.append(f"greater than {_num(spec.gt)}")
    if spec.ge is not None:
        parts.append(f"at least {_num(spec.ge)}")
    if spec.lt is not None:
        parts.append(f"less than {_num(spec.lt)}")
    if spec.le is not None:
        parts.append(f"at most {_num(spec.le)}")
    if not parts:
        return ""
    return " " + " and ".join(parts)


def _choice_text(choices: Sequence[Any]) -> str:
    shown = [_got(choice) for choice in choices]
    if len(shown) == 1:
        return shown[0]
    if len(shown) == 2:
        return f"{shown[0]} or {shown[1]}"
    return "one of " + ", ".join(shown[:-1]) + f", or {shown[-1]}"


def _num(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)


def _got(value: object) -> str:
    if value is None:
        return "nothing"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        shown = value if len(value) <= 40 else value[:37] + "..."
        return f'"{shown}"'
    if type(value) is int:
        return str(value)
    if type(value) is float:
        if math.isnan(value):
            return "a value that is not a number"
        if math.isinf(value):
            return "infinity" if value > 0 else "negative infinity"
        return _num(value)
    if type(value) in (list, tuple):
        return "a list"
    if isinstance(value, Mapping):
        return "a group of named values"
    return type(value).__name__


def _unknown(key: str, names: Sequence[str]) -> str:
    suggestion = _suggest(key, names)
    if suggestion is not None:
        return f'unknown setting "{key}". Did you mean "{suggestion}"?'
    if len(names) <= 12:
        return f'unknown setting "{key}". Expected one of {", ".join(names)}.'
    return f'unknown setting "{key}".'


def _suggest(word: str, names: Sequence[str]) -> str | None:
    folded = word.casefold()
    for name in names:
        if name != word and name.casefold() == folded:
            return name
    best_score = 0.0
    best: list[str] = []
    for name in names:
        score = difflib.SequenceMatcher(None, folded, name.casefold()).ratio()
        if score > best_score:
            best_score = score
            best = [name]
        elif score == best_score:
            best.append(name)
    if best_score < 0.6 or not best:
        return None
    return best[0]


def _join(prefix: str, path: str) -> str:
    if prefix == "":
        return path
    if path == "":
        return prefix
    return f"{prefix}.{path}"


def from_mapping(cls: type[_S], data: Mapping[str, Any]) -> _S:
    """Build a section from a mapping, reporting every problem."""
    _require_plan(cls)
    if not isinstance(data, Mapping):
        raise ConfigError(f"settings must be a group of named values, got {_got(data)}")
    clean: dict[str, Any] = {}
    errors: list[tuple[str, str]] = []
    for key, raw in data.items():
        if type(key) is not str:
            errors.append(("", f"a setting name must be text, got {_got(key)}"))
        else:
            clean[key] = raw
    try:
        built = cast("Callable[..., _S]", cls)(**clean)
    except ConfigError as exc:
        if errors:
            raise ConfigError((*errors, *exc.errors)) from None
        raise
    if errors:
        raise ConfigError(tuple(errors))
    return built


def to_mapping(obj: object) -> dict[str, Any]:
    """Return the section as plain JSON-serialisable data.

    Tuples become lists, mappings become dicts, and nested sections become
    dicts. A whole number stored for a float setting stays a float.
    """
    result: dict[str, Any] = {}
    for item in _require_plan(type(obj)):
        result[item.name] = _plain(getattr(obj, item.name), item)
    return result


def _plain(value: object, item: _Field) -> Any:
    if value is None:
        return None
    if item.kind == "section":
        return to_mapping(value)
    if item.kind == "strings":
        return list(cast("tuple[str, ...]", value))
    if item.kind in ("map_float", "map_str"):
        return dict(cast("Mapping[str, Any]", value))
    return value


def describe(cls: type[object]) -> tuple[FieldInfo | SectionInfo, ...]:
    """Describe a section's groups and leaf settings, in declaration order.

    A nested section is a ``SectionInfo`` immediately before its own rows.
    Each leaf default is the value a fresh instance carries, including a
    nested default that was constructed with overrides. The class passed here
    is the root and has no row of its own.
    """
    _require_plan(cls)
    return tuple(_rows(cls, "", None))


def leaves(cls: type[object]) -> tuple[FieldInfo, ...]:
    """Every leaf setting of a section tree, in declaration order, without group rows."""
    return tuple(row for row in describe(cls) if isinstance(row, FieldInfo))


def _rows(cls: type[object], prefix: str, holder: object | None) -> list[FieldInfo | SectionInfo]:
    rows: list[FieldInfo | SectionInfo] = []
    for item in _require_plan(cls):
        path = _join(prefix, item.name)
        if item.kind == "section":
            rows.append(
                SectionInfo(
                    path=path,
                    help=item.spec.help,
                    audience=item.spec.audience,
                    restart=item.spec.restart,
                    nullable=item.nullable,
                )
            )
            rows.extend(
                _rows(cast("type[object]", item.section), path, _nested_holder(item, holder))
            )
            continue
        value = item.default if holder is None else getattr(holder, item.name)
        rows.append(
            FieldInfo(
                path=path,
                type_name=_TYPE_NAMES[item.kind],
                default=_plain(value, item),
                choices=item.choices if item.kind == "choice" else None,
                ge=item.spec.ge,
                gt=item.spec.gt,
                le=item.spec.le,
                lt=item.spec.lt,
                help=item.spec.help,
                audience=item.spec.audience,
                restart=item.spec.restart,
                nullable=item.nullable,
            )
        )
    return rows


def _nested_holder(item: _Field, holder: object | None) -> object | None:
    candidate = item.default if holder is None else getattr(holder, item.name)
    if type(candidate) is item.section:
        return candidate
    return None


def merge(base: Mapping[str, Any], layer: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-merge two partial documents without validating them.

    A missing key keeps the base value. An explicit None in the layer replaces
    the base value, so a layer can clear an optional setting. When both values
    are mappings, merge key by key; an empty mapping adds and removes nothing.
    Every other layer value, including a list, replaces the base value. The
    result shares no list or mapping with either input.
    """
    if not isinstance(base, Mapping) or not isinstance(layer, Mapping):
        raise TypeError("merge expects two mappings")
    return _merge_maps(base, layer)


def _merge_maps(base: Mapping[str, Any], layer: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in base.items():
        if type(key) is not str:
            raise TypeError("merge keys must be text")
        result[key] = _copy_json(value)
    for key, value in layer.items():
        if type(key) is not str:
            raise TypeError("merge keys must be text")
        current = result.get(key, _MISSING)
        if value is not None and isinstance(value, Mapping) and isinstance(current, Mapping):
            result[key] = _merge_maps(current, value)
        else:
            result[key] = _copy_json(value)
    return result


def _copy_json(value: object) -> Any:
    if isinstance(value, list):
        return [_copy_json(item) for item in value]
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("merge keys must be text")
            copied[key] = _copy_json(item)
        return copied
    return value


__all__ = [
    "Audience",
    "ConfigError",
    "FieldInfo",
    "FieldSpec",
    "SectionInfo",
    "describe",
    "from_mapping",
    "leaves",
    "merge",
    "section",
    "setting",
    "to_mapping",
]
