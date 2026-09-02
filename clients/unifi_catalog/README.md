# HermesStatus UniFi Catalog input

This directory contains the deterministic generated bundle consumed by the
HermesStatus Client. It is a build artifact, not a manually maintained model
database.

- Source repository: 404404/UniFi_Catalog
- Frozen source revision: 813b34eba1dbb7922777897260983ce0189ce39e
- Bundle: catalog.json
- Bundle SHA-256: aa2e5c8f594f1df4e123b32975c0e0dcf333466380013057846381b16288a3b6
- Integrity manifest: catalog.sha256
- Build provenance: catalog-provenance.json

The authoritative lock is `/unifi-catalog.lock.json`. CI checks out the
external repository at that exact revision, runs its validator and tests,
performs two deterministic builds, verifies the locked SHA-256, and stages the
complete bundle here before building the Client image. Do not edit this
generated output manually. Model resolution in HermesStatus accepts only
verified runtime aliases; an administrator-selected collection profile may
explicitly select a canonical SKU.
