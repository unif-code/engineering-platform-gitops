# Vendored controller charts

These charts are retained as reviewed supply-chain inputs. cert-manager and CloudNativePG use
committed `helm template` output plus Kustomize digest transforms. OpenBao is the deliberate
exception: its dormant runtime path creates one `HelmRelease` only after Stage 170 approval, reads
the vendored Chart from the existing GitRepository artifact, and has no HelmRepository or runtime
chart-network dependency.

| Chart | Official source | Version | Package SHA-256 | Registry digest |
| --- | --- | --- | --- | --- |
| cert-manager | `oci://quay.io/jetstack/charts/cert-manager` | `v1.21.1` | `c27101f3f3e2349fb4a9e704316105bf7b52ad73b8c8257d3498ef7f2f6a4adc` | `sha256:15c0b46d9006ce8eb9ff14d1bf54d1bbfcc587bb9e24cd9fe186fb8fec56af1f` |
| cloudnative-pg | `https://cloudnative-pg.github.io/charts` | `0.29.0` | `668e065ff53508d58238788fd35b355a925060843629a951df0e6a9362e6d32f` | not published as the downloaded repository package |
| openbao | `oci://ghcr.io/openbao/charts/openbao` | `0.28.6` | `sha256:175c5cea2d36b68d348eca872044656bd8740c4dbe26b7dc8eb7c7438474a8b3` | `sha256:b3a8d99a56ffa36174b3848917ca849311f890d3bc2214245c88c270a54d0795` |

Generation used Helm `v3.21.0` from
`https://get.helm.sh/helm-v3.21.0-linux-amd64.tar.gz`, verified as
`0093eb572e3d2380f094df162ddb525e219249de88957afe24cfbb19632acd36` before
extraction. Archive entries were checked for absolute paths, parent traversal and
non-file/non-directory types before extraction.

The values used for reproducible rendering are next to each committed `rendered.yaml`:

- `infrastructure/cert-manager/controller/values.yaml`
- `infrastructure/cnpg/controller/values.yaml`
- `infrastructure/openbao/values.yaml`

CloudNativePG chart `0.29.0` renders its operator as a tag. The active Kustomization
replaces that tag with the verified linux/amd64 manifest digest
`sha256:091d306935cfdf646debfe78010d59ebfb572150eb6eb922b0203873c0c68841`.
The corresponding OCI index is
`sha256:a2701eb97cdd2a34b1fdb2cb51987f544b706e40bec72ae7146cd8580efefebb`.

OpenBao Chart `0.28.6` has app version `v2.6.1`. The runtime pins the OpenBao
Server and Agent linux/amd64 manifest to
`sha256:15e90b578c970ae57b596ed51295380cd54f93860fe36758f05b455d71aae0e0`.
The official Chart selects `docker.io/hashicorp/vault-k8s:1.7.2` for its
injector controller; that linux/amd64 manifest is pinned to
`sha256:3dd30a9ac5909d17555480f51be734dfb719a323409f06cffe8b48cdaf6237d2`.
The reviewed package is retained as `openbao-0.28.6.tgz`; its extracted tree is
`vendor/charts/openbao` and contained 60 regular files/directories with no
absolute path, parent traversal, symlink, hardlink or special-file entry.
The committed 16-document reference render is `infrastructure/openbao/rendered.yaml`; its
canonical JSON SHA-256 is
`ee07429197a8ca7644343d0d66b52e3dc7941a8a608fc6db00da3b4184dcc180` after
trailing-whitespace normalization.
