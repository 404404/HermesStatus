# HermesStatus UniFi Catalog input

This directory contains the deterministic generated bundle consumed by the
HermesStatus Client. It is a build artifact, not a manually maintained model
database.

- Source repository: 404404/UniFi_Catalog
- Frozen source revision: 714a3c8ce1a7d6d5165aad66912ea2db5ed55563
- Bundle: catalog.json
- Bundle SHA-256: a92a44e5ef2f4afa20620782f4ecfb539bd72a18f86d5480d4110846f9f4d13b
- Integrity manifest: catalog.sha256
- Build provenance: catalog-provenance.json

The authoritative lock is `/unifi-catalog.lock.json`. CI checks out the
external repository at that exact revision, runs its validator and tests,
performs two deterministic builds, verifies the locked SHA-256, and stages the
complete bundle here before building the Client image. Do not edit this
generated output manually. Model resolution in HermesStatus accepts only
verified runtime aliases; an administrator-selected collection profile may
explicitly select a canonical SKU.
