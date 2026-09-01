# HermesStatus UniFi Catalog input

This directory contains the deterministic generated bundle consumed by the
HermesStatus Client. It is a build artifact, not a manually maintained model
database.

- Source repository: 404404/UniFi_Catalog
- Frozen source revision: 3646c39700c0a063154c1fd787a9e760111c91d3
- Bundle: catalog.json
- Bundle SHA-256: 5caae57981756ca7b0d84a90988ba6b9bfee38cc047cc2e6b7492acffe4f660a
- Integrity manifest: catalog.sha256
- Build provenance: catalog-provenance.json

The authoritative lock is `/unifi-catalog.lock.json`. CI checks out the
external repository at that exact revision, runs its validator and tests,
performs two deterministic builds, verifies the locked SHA-256, and stages the
complete bundle here before building the Client image. Do not edit this
generated output manually. Model resolution in HermesStatus accepts only
verified runtime aliases; an administrator-selected collection profile may
explicitly select a canonical SKU.
