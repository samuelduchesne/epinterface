# epinterface

[![Release](https://img.shields.io/github/v/release/szvsw/epinterface)](https://img.shields.io/github/v/release/szvsw/epinterface)
[![Build status](https://img.shields.io/github/actions/workflow/status/szvsw/epinterface/main.yml?branch=main)](https://github.com/szvsw/epinterface/actions/workflows/main.yml?query=branch%3Amain)
[![codecov](https://codecov.io/gh/szvsw/epinterface/branch/main/graph/badge.svg)](https://codecov.io/gh/szvsw/epinterface)
[![Commit activity](https://img.shields.io/github/commit-activity/m/szvsw/epinterface)](https://img.shields.io/github/commit-activity/m/szvsw/epinterface)
[![License](https://img.shields.io/github/license/szvsw/epinterface)](https://img.shields.io/github/license/szvsw/epinterface)

Dynamically generate EnergyPlus models in Python with idfkit.

- **Github repository**: <https://github.com/szvsw/epinterface/>

## Configuration

The EnergyPlus version used when creating IDF objects can be configured via the `EPINTERFACE_ENERGYPLUS_VERSION` environment variable. It defaults to `22.2.0`. Both dotted (`22.2.0`) and hyphenated (`22-2-0`) version formats are accepted.

- **Documentation** <https://szvsw.github.io/epinterface/>

## Getting started with your project

First, create a repository on GitHub with the same name as this project, and then run the following commands:

```bash
git init -b main
git add .
git commit -m "init commit"
git remote add origin git@github.com:szvsw/epinterface.git
git push -u origin main
```

Finally, install the environment and the pre-commit hooks with

```bash
make install
```

You are now ready to start development on your project!
The CI/CD pipeline will be triggered when you open a pull request, merge to main, or when you create a new release.

To finalize the set-up for publishing to PyPI or Artifactory, see [here](https://fpgmaas.github.io/cookiecutter-uv/features/publishing/#set-up-for-pypi).
For activating the automatic documentation with MkDocs, see [here](https://fpgmaas.github.io/cookiecutter-uv/features/mkdocs/#enabling-the-documentation-on-github).
To enable the code coverage reports, see [here](https://fpgmaas.github.io/cookiecutter-uv/features/codecov/).

## Releasing a new version

- Create an API Token on [PyPI](https://pypi.org/).
- Add the API Token to your projects secrets with the name `PYPI_TOKEN` by visiting [this page](https://github.com/szvsw/epinterface/settings/secrets/actions/new).
- Create a [new release](https://github.com/szvsw/epinterface/releases/new) on Github.
- Create a new tag in the form `*.*.*`.
- For more details, see [here](https://fpgmaas.github.io/cookiecutter-uv/features/cicd/#how-to-trigger-a-release).

---

Repository initiated with [fpgmaas/cookiecutter-uv](https://github.com/fpgmaas/cookiecutter-uv).
