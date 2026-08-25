# Vendored controller charts

These charts are retained as reviewed supply-chain inputs. The active GitOps paths use
committed `helm template` output plus Kustomize digest transforms; the cluster does not
create `HelmRelease`, `HelmRepository`, Helm release-storage Secret, or chart-network
dependency for these two controllers.

| Chart | Official source | Version | Package SHA-256 | Registry digest |
| --- | --- | --- | --- | --- |
| cert-manager | `oci://quay.io/jetstack/charts/cert-manager` | `v1.21.1` | `c27101f3f3e2349fb4a9e704316105bf7b52ad73b8c8257d3498ef7f2f6a4adc` | `sha256:15c0b46d9006ce8eb9ff14d1bf54d1bbfcc587bb9e24cd9fe186fb8fec56af1f` |
| cloudnative-pg | `https://cloudnative-pg.github.io/charts` | `0.29.0` | `668e065ff53508d58238788fd35b355a925060843629a951df0e6a9362e6d32f` | not published as the downloaded repository package |

Generation used Helm `v3.21.0` from
`https://get.helm.sh/helm-v3.21.0-linux-amd64.tar.gz`, verified as
`0093eb572e3d2380f094df162ddb525e219249de88957afe24cfbb19632acd36` before
extraction. Archive entries were checked for absolute paths, parent traversal and
non-file/non-directory types before extraction.

The values used for reproducible rendering are next to each committed `rendered.yaml`:

- `infrastructure/cert-manager/controller/values.yaml`
- `infrastructure/cnpg/controller/values.yaml`

CloudNativePG chart `0.29.0` renders its operator as a tag. The active Kustomization
replaces that tag with the verified linux/amd64 manifest digest
`sha256:091d306935cfdf646debfe78010d59ebfb572150eb6eb922b0203873c0c68841`.
The corresponding OCI index is
`sha256:a2701eb97cdd2a34b1fdb2cb51987f544b706e40bec72ae7146cd8580efefebb`.
