import re
from pathlib import Path


TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def reset_env_flag_if_true(env_file_path: str | Path, flag_name: str) -> bool:
    """Rewrite a True boolean flag in a .env file to False and preserve the process value."""
    env_file = Path(env_file_path)
    if not env_file.exists():
        return False

    lines = env_file.read_text(encoding="utf-8").splitlines(keepends=True)
    assignment_pattern = re.compile(
        rf"^(?P<prefix>\s*(?:export\s+)?{re.escape(flag_name)}\s*=\s*)"
        r"(?P<value>.*?)(?P<newline>\r?\n)?$"
    )

    for index, line in enumerate(lines):
        match = assignment_pattern.match(line)
        if not match:
            continue

        value = match.group("value")
        parsed_value, quote = _parse_env_value(value)
        if parsed_value.lower() not in TRUE_VALUES:
            return False

        newline = match.group("newline") or ""
        lines[index] = f"{match.group('prefix')}{quote}False{quote}{newline}"
        env_file.write_text("".join(lines), encoding="utf-8")
        return True

    return False


def _parse_env_value(raw_value: str) -> tuple[str, str]:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        return value[1:-1], value[0]
    return value.split("#", 1)[0].strip(), ""
