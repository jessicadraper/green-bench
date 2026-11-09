# Contributing to GreenBench

Thanks for your interest in GreenBench! It started as a master's thesis project and is maintained by one person, so this guide is mostly about keeping things manageable for everyone.

## How contributions work

**Issues are always welcome.** Bug reports, questions, confusing documentation, ideas: please open an issue.

**Pull requests start with an issue.** Before writing code, open an issue describing what you'd like to change and why, and wait for a response. This avoids you spending time on something that doesn't fit the project's direction. Small fixes (typos, broken links, obvious one-line bugs) can go straight to a pull request.

Please be patient with response times. This is not a full-time project.

## Reporting a bug

Energy measurement depends heavily on hardware, so please include:

- GreenBench version (`green-bench --version`)
- EnergiBridge version (`energibridge --version`)
- Operating system and version
- CPU / chip (e.g. Apple M1, Intel Core i7-12700, AMD Ryzen 7 5800X)
- Python version
- The full command you ran
- What you expected, and what happened instead
- The relevant part of `output.log` from the results folder, if there is one

If the problem is about the measurements themselves (strange values, zero power), also mention whether you ran with elevated privileges (e.g. `sudo`).

## Setting up for development

```bash
git clone https://github.com/jessicadraper/green-bench
cd green-bench
pip install -e ".[dev]"
```

Most tests don't need energy hardware: they use a fake EnergiBridge.

```bash
pytest -m "not integration"    # unit and CLI tests
ruff check src tests           # lint
```

Tests marked `integration` need a real EnergiBridge installation and hardware access.

## Pull request checklist

- [ ] There is an issue for the change (except small fixes) and it's linked in the PR
- [ ] `pytest -m "not integration"` passes
- [ ] `ruff check src tests` is clean
- [ ] New behaviour has tests
- [ ] User-facing changes are added to `CHANGELOG.md` under **Unreleased**
- [ ] Documentation is updated if options or output changed

Keep pull requests focused on one change. Several small PRs are much easier to review than one large one.

## License

By contributing, you agree that your contributions are licensed under the project's [MIT License](LICENSE).
