# Publishing to PyPI

Harbormaster uses **PyPI Trusted Publishing** (OIDC) — no long-lived API tokens stored in the repo. Tag-pushes to `v*` trigger `.github/workflows/publish.yml`, which builds an sdist + wheel and uploads via short-lived OIDC credentials.

## One-time setup

### 1. Register the project on PyPI

If `harbormaster-mcp` doesn't exist on PyPI yet, register it via the first manual upload:

```bash
# Local one-off (later releases use the workflow):
uv build
uv run python -m twine upload dist/*
```

You'll need an `API_TOKEN` from <https://pypi.org/manage/account/token/> for the first push only.

### 2. Configure Trusted Publishing on PyPI

Navigate to <https://pypi.org/manage/account/publishing/> and add a publisher with:

| Field | Value |
|-------|-------|
| PyPI Project Name | `harbormaster-mcp` |
| Owner | `FleetQ` |
| Repository name | `harbormaster` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

Repeat for TestPyPI at <https://test.pypi.org/manage/account/publishing/> with environment `testpypi` if you want to dry-run releases.

### 3. Create GitHub Environments

In <https://github.com/FleetQ/harbormaster/settings/environments> create two environments:

- `pypi` — optional: require manual approval for production releases.
- `testpypi` — no protection rules needed.

No secrets to add. OIDC handles the auth.

## Releasing

After the one-time setup:

1. Bump `__version__` in `src/harbormaster/__init__.py`.
2. Update `README.md` status section + write `docs/sprint-retro-harbormaster-vX.Y.Z.md`.
3. Commit + push to `main`.
4. Tag and push:
   ```bash
   git tag vX.Y.Z -a -m "Harbormaster vX.Y.Z — <one-line summary>"
   git push origin --tags
   ```
5. The publish workflow triggers automatically. Watch progress at <https://github.com/FleetQ/harbormaster/actions/workflows/publish.yml>.
6. After `pypi` environment approval (if configured), the package lands at <https://pypi.org/project/harbormaster-mcp/>.

## Manual / TestPyPI publish

For dry-runs:

1. Build a tag (or push a tag whose CI already passed).
2. Workflow → "Publish to PyPI" → "Run workflow" → choose `testpypi`.
3. Verify install from TestPyPI:
   ```bash
   uvx --index-url https://test.pypi.org/simple/ harbormaster-mcp --version
   ```

## Verifying a release

Public consumers should be able to install with:

```bash
pipx install harbormaster-mcp[ui]
harbormaster-mcp --version
harbormaster-ui --version
```

For pre-release alphas (`vX.Y.ZaN`), pip needs `--pre`:

```bash
pip install --pre harbormaster-mcp
```

Or via uv:

```bash
uvx --prerelease=allow harbormaster-mcp --version
```
