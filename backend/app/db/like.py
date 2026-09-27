"""LIKE / ILIKE patterns built from user input. `%` and `_` typed by a user are matched literally, never as wildcards
(a query of "%%" must not match every row or defeat the trigram index). Postgres' default LIKE escape is a backslash."""


def escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains(value: str) -> str:
    return f"%{escape(value.strip())}%"


def prefix(value: str) -> str:
    return f"{escape(value.strip())}%"
