# HermesStatus UniFi Catalog input

This directory contains the deterministic generated bundle consumed by the
HermesStatus Client. It is a build artifact, not a manually maintained model
database.

- Source repository: 404404/UniFi_Catalog
- Frozen source revision: a838d664378a328750abed0fb9f622b1f11c5733
- Bundle: catalog.json
- Bundle SHA-256: 1daa97051a6a406d6e4e6b6004fb492a7287d59c4815f33a5c49ef1b54d495e1
- Integrity manifest: catalog.sha256
- Build provenance: catalog-provenance.json

The authoritative lock is `/unifi-catalog.lock.json`. CI checks out the
external repository at that exact revision, runs its validator and tests,
performs two deterministic builds, verifies the locked SHA-256, and stages the
complete bundle here before building the Client image. Do not edit this
generated output manually. Model resolution in HermesStatus accepts only
verified runtime aliases; an administrator-selected collection profile may
explicitly select a canonical SKU.
