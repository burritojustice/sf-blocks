# Changes waiting for a version

Each pull request adds its notes here as `changes/<branch or id>.md`: one `- ` line per change, in plain words, the way they'd read in `CHANGELOG.md`. Don't edit `VERSION` or `CHANGELOG.md` in a pull request.

When the pull request merges, the **Stamp version** action (`scripts/stamp_version.py`) sets `VERSION` to the date (or the next of the day), moves these notes to the top of `CHANGELOG.md` under it, stamps the first line of each script changed since the last version, and removes the files here.

Two pull requests never touch the same lines this way, so they don't conflict.
