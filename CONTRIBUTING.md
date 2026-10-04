# Contributing

Issues and pull requests are welcome. This file holds the maintainer and contributor notes
that used to sit in the README.

## Development

A virtual environment with the pinned Home Assistant release, the test harness and the linter:

```bash
uv venv --python 3.14 .venv          # or: python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements_dev.txt
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The integration is tested against the current stable Home Assistant release and the current
beta, and CI runs both.

## Trying it in a clean Home Assistant

**With Docker** — a throwaway, fresh instance in one command, so you see the same onboarding
and setup a new user gets:

```bash
docker compose up -d        # first run may need: sudo docker compose up -d
```

Open <http://localhost:8123>, complete onboarding, then add the integration and enter the
Meldnummer and Pincode. Useful commands:

```bash
docker compose logs -f homeassistant     # follow the log
docker compose down                      # stop, keep the instance
docker compose down -v                   # stop and throw it away
```

The compose file uses Home Assistant's `stable` image and mounts `custom_components`
read-only, so nothing root-owned lands in your working copy. Change the image tag to `beta`
or to an exact version such as `2026.9.4` to test a different release.

**Without Docker** — a local Home Assistant from the development environment:

```bash
mkdir -p config/custom_components
ln -sfn ../../custom_components/zwolle_parkeerloket config/custom_components/zwolle_parkeerloket
.venv/bin/hass -c config --skip-pip
```

The `config/` directory is gitignored: it holds a throwaway instance, its database and its
storage, and must never contain real credentials in a commit. Delete its `.storage` directory
to start over from onboarding.

> [!IMPORTANT]
> The fixtures under `tests/fixtures` and the placeholders in `tests/helpers.py` are synthetic.
> Never copy real credentials, licence plates or names out of a live account into this
> repository: it is public, and the portal account belongs to a real person.

## Releasing

HACS takes the tag of the newest GitHub release as the version it offers, so a release is what
turns a commit into something users can install and upgrade to. A tag on its own is not enough:
without a release, HACS falls back to the last commit hash.

The tag and `manifest.json` must carry the same version, apart from the conventional `v` prefix
on the tag: HACS reports the tag while Home Assistant displays the manifest version. So a
release goes:

```bash
# 1. Cut the changelog: rename [Unreleased] to the version and the date, leave a fresh empty
#    [Unreleased] on top, and set the same version in manifest.json.
# 2. Commit that, then tag and push it:
git tag -a v1.1.0 -m "1.1.0"
git push origin main
git push origin v1.1.0
# 3. Publish the release, pasting the changelog section in as its notes:
gh release create v1.1.0 --title "1.1.0"
```

The tag has to parse as a version: `1.1.0` and `v1.1.0` are both fine, `release-1.1.0` is not.
Tag a commit on the default branch, since HACS installs the integration out of that tag's
archive.

Step 3 works without the GitHub CLI too: **Releases → Draft a new release**, choose the tag you
just pushed, and paste that changelog section in as the description.

Mark a release as a **pre-release** to use it as a beta channel — HACS hides pre-releases from
users who have not switched on beta versions for the repository.
