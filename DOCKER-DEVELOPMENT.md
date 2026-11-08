# DST Docker development

This private repository holds work on DST's Docker hosting option. It is the same DST product, with the released feature behavior and familiar interface as the parity baseline. The official DST repository continues independently; this repository does not publish releases or authorize changes there.

The intended installation flow is:

1. Windows users install WSL and open Ubuntu. Linux users open their usual terminal.
2. One DST install command prepares the required dependencies and Docker services.
3. The installer displays the local browser portal link; the operator completes setup there.

The Docker edition requires no custom Windows executable. The script behind the install command has passed isolated Ubuntu cold installation and repeated upgrade checks, including first Owner setup, saved ports, certificate retention and host-side Owner recovery. Wider host and game acceptance remain in progress; no public Docker install command has been released.

Full feature parity is still in progress. Keep current DST navigation and workflows; adapt the hosting backend and improve map presentation where needed. Player client configuration uses manual instructions with the complete required INI change list; Docker does not select or edit a player's local game files. Solo stays in the standalone Windows application. Memory balancing remains optional, with its off setting following current DST behavior. VM-data import and Discord portal login are deferred.

Qualification proceeds in bounded native workflows. Opening a route requires direct evidence for its database or lifecycle adapter, permissions and user flow; rendering the inherited interface is insufficient. Consolidate qualified changes before repeating installation acceptance. Runtime credentials, databases, game saves, downloaded official packages, and private test artifacts stay outside this repository.
