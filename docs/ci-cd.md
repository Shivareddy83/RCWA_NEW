# CI/CD

GitHub Actions is defined in `.github/workflows/ci.yml`.

The pipeline runs, in order:

1. checkout
2. Python setup and backend dependency installation
3. full backend regression tests
4. Node 22 setup
5. `npm ci`
6. frontend tests
7. TypeScript typecheck
8. frontend source-hygiene lint
9. production build
10. Docker Compose configuration validation
11. no-cache Docker image build

A failing test, typecheck, build, or Docker build fails the workflow. No deployment credentials are stored in the repository. Deployment credentials, if a future deployment workflow is added, must use GitHub Secrets.

The workflow itself is **implemented but not executed against GitHub in this local review**. Local Docker validation is also blocked because Docker is not installed in the current environment.

## Release discipline

Builds should set `RCAA_VERSION`, `BUILD_ID`, and `GIT_COMMIT_SHA`. A release is identified by the application version plus the source commit/build identifier.

Do not mutate financial data as part of application rollback. If a release is rolled back, keep the database at a schema/data state supported by the replacement application version.
