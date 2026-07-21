# Build Provenance

## Purpose

HermesStatus Server and Client images carry a reviewable identity that links a local or CI artifact to source without embedding credentials or the Git directory. Provenance identifies the build; it is not a signature, attestation, or proof that an image was deployed.

## Build inputs

Both Dockerfiles accept the same non-secret build arguments:

| Argument | Meaning | Required release value |
| --- | --- | --- |
| `VERSION` | Human-readable candidate version | Unique candidate identifier |
| `VCS_REF` | Source revision | Full 40-character lowercase Git SHA |
| `BUILD_DATE` | Build timestamp | UTC RFC3339, for example `2026-07-21T00:00:00Z` |
| `SOURCE_URL` | Public source repository | `https://github.com/404404/HermesStatus` |

The Server embeds `VERSION`, `VCS_REF`, and `BUILD_DATE` in the Go binary. Both final images expose the corresponding OCI labels:

- `org.opencontainers.image.title`
- `org.opencontainers.image.description`
- `org.opencontainers.image.version`
- `org.opencontainers.image.revision`
- `org.opencontainers.image.created`
- `org.opencontainers.image.source`
- `org.opencontainers.image.licenses`

Do not pass credentials, environment files, host paths, private addresses, or deployment identifiers as build arguments or labels.

## Candidate tags

Use a unique local tag such as `hermesstatus-server:2.0-<short-sha>` and `hermesstatus-client:2.0-<short-sha>`. A mutable tag is only a convenient reference. Record the immutable image ID or registry digest before deployment or rollback.

## Validation

After both images are built, run `scripts/validate_image_provenance.py` with the exact build inputs. The validator checks:

- required OCI labels and exact source identity;
- a full Git SHA and UTC build timestamp;
- unchanged Server and Client entrypoints;
- absence of secret-like label content;
- absence of a `.git` directory in either final image.

CI performs this validation in the `images` job. A local pass is not evidence that GitHub Actions ran or that a candidate was deployed.

## Deployment record

Before a reviewed deployment, record only sanitized identity data:

- source branch and full commit SHA;
- short SHA used only in readable tags;
- version and UTC build date;
- Server and Client image references;
- immutable image IDs or registry digests;
- deployment date and Compose project;
- previous Server and Client rollback image IDs or digests;
- Compose project and service names;
- validation result and approval reference.

Do not record environment values, API keys, passwords, Authorization headers, private addresses, or raw runtime configuration.

## Current validation status

| Item | Status |
| --- | --- |
| Provenance validator unit tests | Passed locally |
| Local image validation | Failed - public base-image authorization timed out before either candidate image was produced |
| CI validation | Pending |
| Deployment validation | Pending |
| Production rollback validation | Pending |

The local build failure is an external dependency-fetch failure, not a passed artifact check. Image tags, IDs, labels, and entrypoints remain unavailable until a complete local or CI build succeeds.
