# Tools

Each tool has a schema dict and an `execute_*` function.

## Adding a tool

1. Create `src/backend/tools/my_tool.py` with:
   - `MY_TOOL` — the schema dict (`{"type": "function", "function": {...}}`)
   - `execute_my_tool(arg1, arg2, ...) -> str` — sync or async, returns a string result

2. Register it in `registry.py`:
   - Import the schema and execute function
   - Add the schema to `TOOLS`
   - Add a dispatch branch in `execute_tool`

## Notes

- `execute_tool` is `async`. Wrap sync implementations with `asyncio.to_thread`.
- The bash tool runs commands in a Docker container (see `bash_tool.py`). Container is created on first use, stopped after idle timeout, restarted automatically.
- Memory tools enforce `MEMORY_DIR` path containment via `_safe_resolve`. `SOUL.md` is read-only.
- Cron tools read/write the `cron_jobs` table directly.
