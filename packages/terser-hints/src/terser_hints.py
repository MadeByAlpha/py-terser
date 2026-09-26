preserve_docstring = preserve_annotations = not_none = inline = lambda x: x
constant = lambda x: x()
unreachable = lambda: None


__all__ = (
    "constant",
    "inline",
    "not_none",
    "preserve_annotations",
    "preserve_docstring",
    "unreachable",
)
