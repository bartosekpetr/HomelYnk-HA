# Contributing

Thanks for helping. Bug reports, feature ideas and pull requests are welcome.

## Reporting problems

- **Bugs and feature requests:** open an issue and fill in the form (HA version, integration version, relevant log lines).
- **Security issues:** do **not** open a public issue. Use **Security → Report a vulnerability** or <https://github.com/bartosekpetr/HomelYnk-HA/security/advisories/new>. See [SECURITY.md](SECURITY.md). Never paste controller passwords or backup contents anywhere public.

## Development environment

You need Python 3 and git. A real controller is only needed for the tools in `tools/` and manual testing.

```bash
git clone https://github.com/bartosekpetr/HomelYnk-HA
cd HomelYnk-HA
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install pytest aiohttp
```

To try changes in Home Assistant, copy or symlink `custom_components/wiser_for_knx` into your HA `config/custom_components/` folder and restart HA. See [docs/development.md](docs/development.md) for the manual test checklist.

## Tests

```bash
python -m pytest -q tests
python -m compileall -q custom_components tools tests
```

Home Assistant is not installed for tests: `tests/conftest.py` mocks `homeassistant.*`, so only pure code (`widgets.py`, `backup_utils.py`, parts of `api.py`, `health.py`) is really exercised. Config flow, scheduler, registries and services must be verified in a real HA; say in your PR what you tested.

## Lint and style

No linter is configured yet. Match the surrounding code and keep changes focused; if you run `ruff` locally, do not reformat untouched code.

## Pull requests

- One change per PR, with the behaviour change explained.
- Add a test where the code is testable (see above).
- Do not commit controller dumps, passwords or backups (`tools/` writes these locally and they are git-ignored).

By contributing you agree your work is released under the repository's [LICENSE](LICENSE).
