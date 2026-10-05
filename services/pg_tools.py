"""Find the newest installed PostgreSQL client without using shell commands."""

import asyncio
import os
import re
import shutil
from pathlib import Path

from decouple import config


async def find_pg_tool(name):
    override = config(f"{name.upper()}_PATH", default="")
    if override:
        return override
    found = shutil.which(name)
    candidates = {found} if found else set()
    candidates.update(
        str(path) for path in Path("/usr/lib/postgresql").glob(f"*/bin/{name}")
    )
    if os.name == "nt":
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(variable)
            if root:
                candidates.update(
                    str(path)
                    for path in (Path(root) / "PostgreSQL").glob(f"*/bin/{name}.exe")
                )
    versions = []
    for candidate in candidates:
        try:
            process = await asyncio.create_subprocess_exec(
                candidate,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                output, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            except BaseException:
                process.kill()
                await process.wait()
                raise
            match = re.search(rb"(\d+)(?:\.(\d+))?", output)
            if not process.returncode and match:
                versions.append(
                    (tuple(int(part or b"0") for part in match.groups()), candidate)
                )
        except (OSError, asyncio.TimeoutError):
            continue
    return max(versions)[1] if versions else name


async def communicate(process):
    try:
        return await asyncio.wait_for(
            process.communicate(), config("PG_TOOL_TIMEOUT", default=900, cast=int)
        )
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
