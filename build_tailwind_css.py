"""Hatchling build hook: compile Tailwind v4 CSS at wheel-build time.

When the maintainer runs ``uv build`` or ``hatch build`` we want the
emitted wheel to ship a freshly-compiled
``src/harbormaster/ui/static/tailwind.css`` so end users can do
``uvx harbormaster-mcp`` with **zero Node toolchain** — the CSS is
just a static asset bundled in the wheel.

Compilation strategy:

1. Locate ``npx``. If it's missing (Node isn't installed on the build
   host), skip compilation and assume the committed
   ``src/harbormaster/ui/static/tailwind.css`` is current. The hook
   warns but does not fail — sdist builds on Node-less CI still work.
2. Install ``tailwindcss`` + ``@tailwindcss/cli`` into a build-temp
   ``node_modules`` (so ``@import "tailwindcss"`` resolves), then
   symlink that ``node_modules`` next to the input CSS so the
   Tailwind v4 resolver finds it.
3. Run the CLI, minified, writing to the in-tree static path.
4. Sanity-check: output must exist, be > 0 bytes, contain the
   ``--color-accent`` token (the canonical "did the @theme block
   make it through" probe).
5. Clean up the symlink (the wheel must not ship it).

The hook is registered in pyproject.toml under
``[tool.hatch.build.targets.wheel.hooks.custom]``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


_INPUT_REL = "src/harbormaster/ui/static/tailwind.input.css"
_OUTPUT_REL = "src/harbormaster/ui/static/tailwind.css"
_PROBE_TOKEN = "--color-accent"


class TailwindBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    """Compile Tailwind v4 CSS prior to wheel assembly."""

    PLUGIN_NAME = "tailwind-css"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version, build_data  # unused; required by hatch hook contract
        root = Path(self.root)
        input_path = root / _INPUT_REL
        output_path = root / _OUTPUT_REL

        if not input_path.exists():
            # No source file → nothing to do. Lets non-UI variants of
            # this repo (if anyone ever forks the package without the
            # UI surface) skip cleanly.
            return

        npx = shutil.which("npx")
        if npx is None:
            self.app.display_warning(
                "build_tailwind_css: npx not found on PATH; "
                f"using committed {_OUTPUT_REL} as-is. Install Node "
                "to refresh the bundled stylesheet."
            )
            self._verify_output(output_path)
            return

        with tempfile.TemporaryDirectory(prefix="hm-tw-build-") as tmp:
            tmp_path = Path(tmp)

            self.app.display_info(
                "build_tailwind_css: installing tailwindcss + "
                "@tailwindcss/cli into a temp prefix"
            )
            subprocess.run(
                [
                    "npm",
                    "install",
                    "--silent",
                    "--no-audit",
                    "--no-fund",
                    "--no-package-lock",
                    "--prefix",
                    str(tmp_path),
                    "tailwindcss@latest",
                    "@tailwindcss/cli@latest",
                ],
                check=True,
            )

            # The CLI resolves `@import "tailwindcss"` from the
            # input file's directory upward. Symlink the temp
            # node_modules into static/ so resolution succeeds; we
            # remove the symlink before returning so the wheel
            # never sees it.
            link_target = tmp_path / "node_modules"
            link_path = input_path.parent / "node_modules"
            try:
                if link_path.exists() or link_path.is_symlink():
                    link_path.unlink()
                os.symlink(link_target, link_path)

                self.app.display_info(
                    f"build_tailwind_css: compiling {_INPUT_REL} → "
                    f"{_OUTPUT_REL}"
                )
                subprocess.run(
                    [
                        npx,
                        "--no-install",
                        "@tailwindcss/cli",
                        "-i",
                        str(input_path),
                        "-o",
                        str(output_path),
                        "--minify",
                    ],
                    cwd=str(tmp_path),
                    check=True,
                )
            finally:
                if link_path.is_symlink():
                    link_path.unlink()

        self._verify_output(output_path)

    def _verify_output(self, output_path: Path) -> None:
        if not output_path.exists():
            raise RuntimeError(
                f"build_tailwind_css: expected {output_path} to exist "
                "after build (or as a committed fallback). "
                "Run `npx @tailwindcss/cli` manually to seed it."
            )
        size = output_path.stat().st_size
        if size == 0:
            raise RuntimeError(
                f"build_tailwind_css: {output_path} is 0 bytes — "
                "compilation produced an empty file."
            )
        text = output_path.read_text(encoding="utf-8", errors="ignore")
        if _PROBE_TOKEN not in text:
            raise RuntimeError(
                f"build_tailwind_css: {output_path} does not contain "
                f"the canonical probe token {_PROBE_TOKEN!r}; "
                "the @theme block may have been dropped."
            )
        self.app.display_info(
            f"build_tailwind_css: ok — {size} bytes, probe token present"
        )
