# HermesStatus UniFi Catalog input

This directory contains the deterministic generated bundle consumed by the
HermesStatus Client. It is a build artifact, not a manually maintained model
database.

- Source repository: 404404/UniFi_Catalog
- Frozen source revision: 2a8991933b5f4a323c27c30d9370ec3836d749b4
- Bundle: catalog.json
- Bundle SHA-256: 52b4313e9c619f13af7ba64a19fb69d2259092586eed0af4f8e698f32e577791
- Integrity manifest: catalog.sha256
- Build provenance: catalog-provenance.json

The authoritative lock is `/unifi-catalog.lock.json`. CI checks out the
external repository at that exact revision, runs its validator and tests,
performs two deterministic builds, verifies the locked SHA-256, and stages the
complete bundle here before building the Client image. Do not edit this
generated output manually. Model resolution in HermesStatus accepts only
verified runtime aliases; an administrator-selected collection profile may
explicitly select a canonical SKU.
