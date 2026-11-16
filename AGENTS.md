# Baton agent instructions

## Project identity

Baton is a health-tech platform built as a single Django monolith. The backend
uses Python and Django; the frontend uses Django Templates, HTML and CSS.

## Architecture

- Prefer conventional Django patterns and the existing project structure.
- Do not introduce separate frontend and backend applications.
- Avoid unnecessary abstractions and dependencies. Keep implementation
  proportional to current requirements.
- Use SQLite for local development. Create additional Django apps only when
  implemented functionality warrants them.

## Development discipline

- Review the requirements before implementation. Do not silently expand scope
  or implement unapproved features.
- Validate inputs on the server and apply appropriate permissions and
  authorization checks.
- Write tests for implemented functionality, including meaningful failure cases.
- Fix root causes rather than hiding defects.
- Update documentation when behavior, configuration or setup changes.

## Security

- Never commit secrets, local environment files, databases or health information.
- Treat health information as sensitive; avoid exposing it in logs, fixtures or
  examples.
- Validate and authorize sensitive operations server-side.
- Use Django's built-in security mechanisms appropriately, including CSRF
  protection, authentication, password validation and template autoescaping.
- Keep configuration in environment variables and require a secret key without
  a hardcoded fallback.

## UI development

Read and follow [.agents/skills/ui/SKILL.md](.agents/skills/ui/SKILL.md) whenever
implementing or modifying user interfaces.

## Workflow

- Inspect relevant existing code before changing it. Keep changes focused.
- Use uv for dependency management and execution. Commit `pyproject.toml` and
  `uv.lock` together when dependencies change.
- Run Django commands with `uv run python manage.py ...` after setting up the
  local environment as described in the README. Settings automatically load the
  project-root `.env` without overriding process environment variables.
- Run relevant tests and Django system checks for implemented functionality.
- Report implementation decisions, verification results and outstanding issues.
  Do not claim tests passed unless they were actually executed.
