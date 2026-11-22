"""The SBEM data model imports without archetypal, eppy or a generated Prisma client."""

import subprocess
import sys
import textwrap

import pytest

# Modules that must not be needed to describe an SBEM archetype. `prisma` is
# blocked as a whole, which also covers a client that was never generated.
BLOCKED = ("archetypal", "eppy", "geomeppy", "prisma")

MODULES = (
    "epinterface.sbem.archetype",
    "epinterface.sbem.components",
    "epinterface.sbem.components.zones",
    "epinterface.sbem.components.composer",
    "epinterface.sbem.builder",
)


@pytest.mark.parametrize("module", MODULES)
def test_imports_without_blocked_modules(module: str):
    """Importing the module neither needs nor loads a blocked package."""
    script = textwrap.dedent(
        f"""
        import importlib
        import importlib.abc
        import sys

        BLOCKED = {BLOCKED!r}

        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in BLOCKED:
                    raise ImportError(f"blocked: {{name}}")
                return None

        sys.meta_path.insert(0, Blocker())
        importlib.import_module({module!r})
        loaded = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED)
        assert not loaded, loaded
        """
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
