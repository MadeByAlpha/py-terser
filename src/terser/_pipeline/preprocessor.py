import io
import re
import tokenize
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Final


def _comments(source: str) -> dict[int, tuple[int, str]] | None:
    """
    `{line number: (column, text)}` of every real comment in `source` (1-indexed lines).

    Directive handling works on comment tokens rather than raw lines, so text that only looks like
    a comment - e.g. a line starting with `#` inside a multi-line string - is never mistaken for one.
    None if the source doesn't tokenize; the later parse step raises a proper error for it.
    """

    comments: dict[int, tuple[int, str]] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                comments[tok.start[0]] = (tok.start[1], tok.string.rstrip())
    except (tokenize.TokenError, SyntaxError):
        return None

    return comments


__DIRECTIVES: Final[Mapping[str, Mapping[bool, re.Pattern]]] = {
    "if": {
        True: re.compile(r"^#\s?if ([A-Za-z_][A-Za-z0-9_]*)$"),
        False: re.compile(r"^#\s*if\s+([A-Za-z_][A-Za-z0-9_]*)$")
    },
    "elif": {
        True: re.compile(r"^#\s?elif ([A-Za-z_][A-Za-z0-9_]*)$"),
        False: re.compile(r"^#\s*elif\s+([A-Za-z_][A-Za-z0-9_]*)$")
    },
    "else": {
        True: re.compile(r"^#\s?else$"),
        False: re.compile(r"^#\s*else$")
    },
    "endif": {
        True: re.compile(r"^#\s?endif$"),
        False: re.compile(r"^#\s*endif$")
    },
}


def preprocess(source: str, defines: Mapping[str, bool] | None, strict: bool = False) -> tuple[str, str | None]:
    """
    Evaluate `# if NAME` / `# elif NAME` / `# else` / `# endif` directives, and inline
    `code  # if NAME` directives.

    Every dropped line (comments, directives, lines of inactive blocks, the shebang) is replaced
    with an empty line, so line numbers in later errors still match the original source.

    :param source: The module source
    :param defines: Values of the directive names. Undefined names count as True
    :param strict: Only accept the exact `#if NAME`/`# if NAME` spelling, and raise SyntaxError
        for unbalanced directives
    :return: The preprocessed source, and the shebang line if there was one
    """

    lines = source.splitlines()
    if not lines:
        return "", None

    shebang = lines[0] if lines[0].startswith("#!") else None
    defines: Mapping[str, bool] = defines or {}

    comments = _comments(source)
    if comments is None:
        return '\n'.join(["", *lines[1:]] if shebang is not None else lines), shebang

    def error(message: str, lineno: int):
        return SyntaxError(message, ("<preprocessor>", lineno, 1, lines[lineno - 1]))

    # one (active, taken) pair per open block: whether its current branch is active, and whether
    # any of its branches has been taken already
    stack: list[tuple[bool, bool]] = []
    keeping = lambda: all(active for active, _ in stack)

    output: list[str] = []
    for lineno, line in enumerate(lines, start=1):
        if lineno == 1 and shebang is not None:
            output.append("")
            continue

        comment = comments.get(lineno)
        if comment is None:
            output.append(line if keeping() else "")
            continue

        column, text = comment
        if line[:column].strip():
            # inline comment after code
            if not keeping():
                output.append("")
            elif (match := __DIRECTIVES["if"][strict].match(text)) and not defines.get(match.group(1), True):
                output.append("")
            else:
                output.append(line[:column].rstrip() if match else line)
            continue

        # a comment on its own line: dropped either way
        output.append("")

        if match := __DIRECTIVES["if"][strict].match(text):
            defined = defines.get(match.group(1), True)
            stack.append((defined, defined))
        elif match := __DIRECTIVES["elif"][strict].match(text):
            if not stack:
                if strict:
                    raise error("'# elif' without '# if'", lineno)
                continue

            _, taken = stack.pop()
            defined = defines.get(match.group(1), True)
            stack.append((defined and not taken, taken or defined))
        elif __DIRECTIVES["else"][strict].match(text):
            if not stack:
                if strict:
                    raise error("'# else' without '# if'", lineno)
                continue

            _, taken = stack.pop()
            stack.append((not taken, True))
        elif __DIRECTIVES["endif"][strict].match(text):
            if not stack:
                if strict:
                    raise error("'# endif' without '# if'", lineno)
                continue

            stack.pop()

    if stack and strict:
        raise error("'# if' without '# endif'", len(lines))

    return '\n'.join(output), shebang
