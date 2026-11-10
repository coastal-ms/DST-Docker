# Security policy

The latest [DST Docker release](https://github.com/coastal-ms/DST-Docker/releases/latest) receives security fixes. Upgrade by rerunning the Docker installer with the same installation path.

## Report a vulnerability

Report security problems privately through [GitHub security advisories](https://github.com/coastal-ms/DST-Docker/security/advisories/new), or contact Coastal in the [community Discord](https://discord.gg/tj2x7cywSC). Include the DST Docker version, impact and reproduction steps. Remove credentials and private server or player information from attachments. Disclosure is coordinated with the reporter.

## Release integrity

The bootstrap resolves the latest release tag to its source commit and downloads that commit’s source from GitHub over HTTPS. It validates archive paths and entry types before running the installer. Releases use GitHub’s automatically generated source archives.

This policy covers DST Docker's browser application, native hosting adapters and installer. Funcom publishes and maintains the underlying Dune Awakening server software separately.
