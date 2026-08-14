# Kubelet package footprint compatibility design

## Context

On Ubuntu 24.04, the approved `kubelet` package installs this exact footprint before `kubeadm init`:

- `/etc/kubernetes`: directory, `0775`, `root:root`, owned by package `kubelet`;
- `/etc/kubernetes/manifests`: directory, `0775`, `root:root`, owned by package `kubelet`;
- `/etc/kubernetes/manifests/.kubelet-keep`: regular non-symlink file, `0644`, `root:root`, zero bytes, owned by package `kubelet`.

The empty file has SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

The same approved package also installs a second exact pre-init footprint:

- `/var/lib/kubelet`: directory, `0775`, `root:root`, owned by package `kubelet`;
- `/var/lib/kubelet/.kubelet-keep`: regular non-symlink file, `0644`, `root:root`, zero bytes, owned by package `kubelet`.

The second placeholder has the same approved empty-file SHA-256. It is package payload, not kubelet-generated configuration or node identity state.

Stage 40 correctly accepts the installed package state, but Stage 50 originally recognized neither package footprint. After recognizing `/etc/kubernetes`, its pre-init input gate still rejects the exact `/var/lib/kubelet` package footprint as `kubelet-root-mode-unsafe`, even though the root contains no generated configuration or identity state.

## Decision

Preserve the package-owned files and extend the Stage 50 state model with exact, fail-closed package footprints for both package-owned roots. Do not delete either `.kubelet-keep`, change package-owned directory modes, or weaken the generic missing/empty-root rules.

## Fresh-state contract

`initialization_state` may classify the host as `FRESH` when either the existing missing/safe-empty contract passes or all of the following package-footprint conditions pass:

1. `/etc/kubernetes` is a real directory, not a symlink, mode `0775`, owned by the expected root identity, and `dpkg-query -S` returns exactly `kubelet: /etc/kubernetes`.
2. Its only direct entry is `manifests`.
3. `/etc/kubernetes/manifests` is a real directory, not a symlink, mode `0775`, owned by the expected root identity, and `dpkg-query -S` returns exactly `kubelet: /etc/kubernetes/manifests`.
4. Its only direct entry is `.kubelet-keep`.
5. `.kubelet-keep` is a regular non-symlink file, mode `0644`, owned by the expected root identity, zero bytes, has the approved empty-file SHA-256, and `dpkg-query -S` returns exactly `kubelet: /etc/kubernetes/manifests/.kubelet-keep`.
6. `/var/lib/etcd` still satisfies the existing missing-or-safe-empty contract.
7. No process listens on TCP port 6443.

Any missing record, duplicate output, extra path, symlink, unreadable state, metadata drift, non-empty placeholder, digest drift, unexpected package owner, etcd state, or API listener remains fail-closed.

## Kubelet pre-init input contract

The existing missing-root and safe-empty `/var/lib/kubelet` states remain valid. A non-empty root is accepted only when all of the following package-footprint conditions pass:

1. `/var/lib/kubelet` is a real directory, not a symlink, mode `0775`, owned by the expected root identity, and `dpkg-query -S` returns exactly one terminated line: `kubelet: /var/lib/kubelet`.
2. Its only direct entry is `.kubelet-keep`; descendants, additional directories, files, and broken symlinks are rejected.
3. `.kubelet-keep` is a regular non-symlink file, mode `0644`, owned by the expected root identity, zero bytes, has the approved empty-file SHA-256, and `dpkg-query -S` returns exactly one terminated line: `kubelet: /var/lib/kubelet/.kubelet-keep`.
4. The existing explicit rejection of `kubeadm-flags.env`, `config.yaml`, `instance-config.yaml`, and `pki` remains in place.

Mode `0775` is never accepted merely because the directory is empty or contains a file named `.kubelet-keep`; it is bound to the exact filesystem metadata, entry set, digest, and package provenance above. Failed queries, non-zero commands with output, missing or duplicate records, trailing blank lines, additional owner records, and any mutation remain fail-closed.

## Initialized-state contract

The initialized candidate and post-init verifier must preserve the existing control-plane checks while accounting for package-owned directory metadata:

- `/etc/kubernetes` mode `0755` remains accepted. Mode `0775` is accepted only when the path is a real root-owned directory and has the exact `kubelet` package ownership record.
- `/etc/kubernetes/manifests` mode `0700` remains accepted. Mode `0775` is accepted only under the same exact package-owned condition.
- The manifest directory must contain either exactly the four approved static Pod manifests, or those four manifests plus an exact approved `.kubelet-keep` file.
- If `.kubelet-keep` is present after `kubeadm init`, its metadata, size, digest, and package ownership are revalidated. No other fifth entry is allowed.

This permits either behavior from `kubeadm`: preserving the package placeholder or removing it. It does not permit arbitrary group-writable Kubernetes directories because `0775` is bound to the installed package record.

## Execution and race behavior

`--check` remains zero-write. `--apply` does not normalize or delete either footprint. The existing repeated fresh-state and kubelet pre-init gates before validation, preflight, and init re-run the complete package-footprint checks, so a mutation between phases stops before `kubeadm init`.

After `kubeadm init`, the existing initialized control-plane gate revalidates the directory and placeholder contracts before evidence is emitted.

## Test strategy

Add load-bearing tests that prove:

- the exact official package footprint reaches `PASS_KUBEADM_CHECK` and can proceed through `--apply`;
- repeated gates detect mutations before `kubeadm init`;
- extra entries, directory and file symlinks, mode/owner drift, non-empty bytes, size/digest drift, missing or wrong package ownership, etcd state, and a 6443 listener are rejected;
- initialized state accepts the four manifests with or without the exact placeholder;
- an unknown fifth manifest entry or placeholder provenance drift is rejected;
- existing truly empty, partial-state, and already-initialized behavior remains unchanged.
- the exact `/var/lib/kubelet` package footprint is zero-write in `--check` and can proceed through `--apply`;
- root/placeholder type, mode, filesystem owner, package owner, entry set, bytes, size, digest, and owner-output shape drift are independently rejected;
- mutations after validate and after preflight are detected before `kubeadm init` consumes state.

## Scope

Only Stage 50 state recognition/pre-init input validation and its tests change. Stage 40 package verification, kubeadm configuration, package versions, manifests, Cilium, evidence format, and server cleanup behavior remain unchanged.
