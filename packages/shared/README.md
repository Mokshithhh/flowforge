# Shared Contracts

The MVP currently keeps Pydantic API schemas in `apps/api/app/schemas.py` and the corresponding TypeScript shapes alongside the frontend API client in `apps/web/src/App.tsx`. Move these to generated OpenAPI types before adding another client runtime; this folder is intentionally not populated with a second hand-maintained contract copy.
