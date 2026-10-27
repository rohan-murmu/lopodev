# Installation and release

## Requirements

- Python 3.12+ for the CLI and existing deterministic scripts.
- Blender is optional for existing Godot projects; required only for modeling
  and asset generation. Blender MCP is optional and requires its Blender addon
  server to be running.
- Godot is required for project import/runtime/build checks. The toolkit's
  existing `tools/env.sh` can locate its pinned Linux binary or a `godot` on
  `PATH`; other OS builds should configure `GODOT` explicitly.
- Android export additionally needs matching Godot Android templates, Android
  SDK/build-tools, JDK 17, and a debug or release keystore. AAB distribution also
  needs Godot's Gradle Android template and release signing. See
  [`android-export.md`](android-export.md).
- OpenCode, Kilo, Cursor, and the MCP SDK are optional and only needed for their
  corresponding integration.

## Checkout install

From this checkout:

```sh
./bin/lopodev --version
./bin/lopodev doctor
./bin/lopodev install opencode --project /path/to/workspace --dry-run
./bin/lopodev install opencode --project /path/to/workspace
```

Equivalent targets: `kilo`, `cursor`, and `mcp`. Use
`lopodev uninstall <target> --dry-run` to preview a safe cleanup. Installers report each path,
preserve unrelated existing files, and require the user to manually merge MCP
registration into a client config. `doctor` reports missing optional tools but
does not install software or change system settings.
The generated OpenCode config keeps Blender MCP disabled until the user enables
it; this avoids making the addon/server an installation prerequisite.

`bin/lopodev` is the CLI. `tools/install_lopodev.sh` remains as a deprecated
compatibility wrapper. On Windows, invoke the CLI with
`python tools/lopodev_cli.py` until a native Windows launcher is supplied.

## Homebrew status and release workflow

The GitHub repository is confirmed as `https://github.com/rohan-murmu/lopodev`,
and the local `origin` now points there. There are currently no release tags or
published release archives. The repository now ships an MIT `LICENSE`. The new
`.github/workflows/release.yml` builds a version-matched source tarball and
SHA-256 sidecar when a `v*` tag is pushed. Do not claim public Homebrew
availability until a release is published and the formula is installed/tested
from that release.

After a versioned archive is published, download
the exact release asset and generate a tap formula. The helper computes and
prints the SHA-256 from the supplied bytes; it does not guess a digest. The
release URL pattern is
`https://github.com/rohan-murmu/lopodev/releases/download/v<VERSION>/lopodev-<VERSION>.tar.gz`.

```sh
python3 tools/homebrew_formula.py \
  --version <confirmed-version> \
  --archive-file lopodev-<version>.tar.gz \
  --license <confirmed-SPDX-license> \
  --output Formula/lopodev.rb
brew style Formula/lopodev.rb
brew audit --strict --new --formula Formula/lopodev.rb
brew install --build-from-source ./Formula/lopodev.rb
brew test lopodev
```

This generator intentionally refuses missing or malformed release metadata and
refuses to overwrite a formula. It is not a substitute for running Homebrew on
the actual release archive. Put the generated formula in a separate public tap
repository (for example `homebrew-lopodev`) to support
`brew tap rohan-murmu/lopodev`; a formula committed only here does not create a
tap at that name.

For future updates: update `VERSION`, publish a new versioned tagged archive,
download it and generate the formula (which computes its SHA-256), then run the
formula audit, install and test.
Installed users update with `brew update && brew upgrade lopodev`.
