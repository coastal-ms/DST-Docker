# DST Docker development

This private repository holds work on DST's Docker hosting option. It is the same DST product, with the released feature behavior and familiar interface as the parity baseline. The official DST repository continues independently; this repository does not publish releases or authorize changes there.

The intended installation flow is:

1. Windows users install WSL and open Ubuntu. Linux users open their usual terminal.
2. One DST install command prepares the required dependencies and Docker services.
3. The installer displays the local browser portal link; the operator completes setup there.

The Docker edition should require no custom Windows executable. Installer progress, recoverable failures, existing-install detection, persistent configuration, and updates belong in the supported flow. The single-command installer and clean-machine acceptance remain unfinished.

Full feature parity is still in progress. Keep current DST navigation and workflows; adapt the hosting backend and improve map presentation where needed. Browser access to a player's own client configuration requires an explicit browser file workflow. Memory balancing must be optional, with its off setting following current DST behavior. VM-data import and Discord portal login are deferred.

The initial source snapshot comes from Docker development checkpoint `bce85944`. Runtime credentials, databases, game saves, downloaded official packages, and private test artifacts are outside this repository.
