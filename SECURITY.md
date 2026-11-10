# Security policy

The latest [DST Docker release](https://github.com/coastal-ms/DST-Docker/releases/latest) receives security fixes. Upgrade by rerunning the Docker installer with the same installation path.

## Report a vulnerability

Report security problems privately through [GitHub security advisories](https://github.com/coastal-ms/DST-Docker/security/advisories/new), or contact Coastal in the [community Discord](https://discord.gg/tj2x7cywSC). Include the DST Docker version, impact and reproduction steps. Remove credentials and private server or player information from attachments. Disclosure is coordinated with the reporter.

## Release integrity

Download `dst-docker-install.sh` and `SHA256SUMS` from this repository's release page. Check a downloaded installer with `sha256sum --check SHA256SUMS`. The installer includes its source commit and version, available with `bash dst-docker-install.sh --version`.

This policy covers DST Docker's browser application, native hosting adapters and installer. Funcom publishes and maintains the underlying Dune Awakening server software separately.
