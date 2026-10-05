"""Lossless JSON representation of application rows and cached metadata."""

import base64
import re
from datetime import datetime


def parse_timestamp(value):
    """Normalize PostgreSQL's variable fraction/offset notation for Python 3.10."""
    value = str(value).replace("Z", "+00:00")
    if re.search(r"\d\d:\d\d:\d\d\.\d{7,}", value):
        raise ValueError("Timestamp precision exceeds microseconds")
    value = re.sub(
        r"(\d\d:\d\d:\d\d)\.(\d{1,6})(?=[+-]|$)",
        lambda match: match[1] + "." + match[2].ljust(6, "0"),
        value,
    )
    if re.search(r"[T ]\d\d:", value):
        value = re.sub(r"([+-]\d\d)$", r"\1:00", value)
        value = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", value)
    return datetime.fromisoformat(value)


def encode_row(row):
    return {
        key: {"$bytes": base64.b64encode(value).decode("ascii")}
        if isinstance(value, bytes)
        else value.isoformat()
        if isinstance(value, datetime)
        else value
        for key, value in row.items()
    }


def decode_row(table, row):
    result = dict(row)
    for column in table.columns:
        value = result.get(column.name)
        if value is None:
            continue
        python_type = column.type.python_type
        if python_type is bytes and isinstance(value, dict):
            result[column.name] = base64.b64decode(value["$bytes"], validate=True)
        elif python_type is datetime and isinstance(value, str):
            result[column.name] = parse_timestamp(value)
    return result
