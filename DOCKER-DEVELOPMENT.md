# DST Docker development

DST Docker is a separate product for browser-based Dune Awakening server hosting on Linux and Windows WSL. Its product name, version, repository and release asset names are defined in `packaging/docker/release.json`. The Linux entry point reads this identity directly. Windows Dune Server Tool versions and updates are independent.

## Local setup

From a committed checkout, run `bash bin/dst-install --source "$PWD"`. The normal user installation downloads the standalone shell installer described in README.md. Game data, credentials and local evidence stay outside the repository.

## Release assets

Build from an explicit clean source commit:

```sh
python3 packaging/docker/build_release.py --revision COMMIT --output /path/to/assets
```

The output contains `dst-docker-install.sh`, `SHA256SUMS`, release notes, the product/source manifest and a version-pinned install command. The builder reads both source and installer template from the selected Git commit. It does not publish, tag, upload or change repository visibility.

The release repository is `coastal-ms/DST-Docker`. The Windows product repository and website are separate; inherited website deployment workflows are restricted to their original repository.

## Runtime boundaries

The browser service is unprivileged and has no Docker socket. Typed manager and host-session adapters expose bounded operations. Native Linux uses Docker's normal startup behavior; the Windows desktop launcher owns an explicit foreground WSL hosting session. Keep platform-specific controls out of native Linux screens.

Use targeted Python, Pester and frontend tests for changed behavior, then build and exercise the packaged installer in an isolated installation. Preserve other hosting installations and their data.
