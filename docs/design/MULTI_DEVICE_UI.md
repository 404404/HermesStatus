# HermesStatus 2.2 Multi-Device UI

Status: Stage E local implementation complete; production deployment remains
disabled.

## 1. Current UI audit

The current dashboard fetches one stats document, stores one `lastDocument`,
creates one view model, and has one automatic refresh timer. Its
`selectSingleHost(servers)` helper always selects the first enabled server (or
the first server), which is why an already multi-item `servers[]` document
still renders only one node.

The primary navigation is already correct:

- Home
- Docker
- Lucky

2.2 keeps this navigation and adds one shared secondary device selector. It
does not add an all-device aggregate page.

## 2. State model

The dashboard adds only:

```text
selectedDeviceId
deviceSelectionNotice
```

It retains:

- one normalized `currentStats`/`lastDocument`;
- one controller;
- one active primary page;
- one manual refresh action;
- one automatic refresh timer.

Rendering derives `selectedDevice` from `currentStats.servers` and
`selectedDeviceId`. Device switching is a local state/render operation. It
must not fetch stats, create a timer, restart a timer, or establish another
stream.

The frozen stats field carrying the stable ID is `device_id`. Internal
JavaScript state remains `selectedDeviceId`; this naming difference is
intentional.

## 3. Selector

Every primary page renders the same selector:

- desktop: compact device buttons/tabs;
- mobile: accessible `<select>`;
- each option shows canonical display name and an
  online/degraded/stale/offline/never-seen badge;
- an optional short ID may be displayed, but no FQDN/address is needed.

Enabled devices remain selectable while offline, stale, or never seen.
Disabled devices are excluded from normal selection. If no enabled device
exists, the page shows a bounded configuration-empty state without throwing.

Selector input is generated from the normalized, bounded stats contract.
Labels are escaped/text-bound exactly like current dashboard content.

## 4. Hash routing

Canonical routes are:

```text
#home?device=gk50-hermes
#docker?device=gk50-hermes
#lucky?device=gk50-hermes
```

Legacy routes remain valid:

```text
#home
#docker
#lucky
```

Parsing rules:

1. split the hash at the first `?`;
2. validate the page against the fixed page allowlist;
3. parse the query with `URLSearchParams`;
4. accept exactly one syntactically valid `device` value;
5. require it to exist as an enabled device in the current document;
6. ignore/rewrite duplicates and unknown parameters in the canonical URL.

The current parser must not lowercase the entire hash, because device IDs are
validated separately and query parsing must be structural. IDs are already
lower-case by contract.

Changing the primary page keeps the selected device. Changing the device keeps
the primary page. History updates use a safely constructed hash; raw input is
never concatenated into HTML.

## 5. Selection precedence and recovery

After every successful stats normalization:

1. valid enabled device from the URL;
2. valid enabled device stored in localStorage;
3. valid enabled `default_device_id`;
4. first enabled device in stable stats order.

Only a validated ID is stored. Local storage contains no display metadata,
FQDN, stats, credential, or configuration.

An invalid/missing/removed selection:

- falls back using the rules above;
- replaces the URL with the canonical route;
- updates localStorage;
- displays a short non-sensitive notice;
- does not throw or make an extra request.

If the selected device remains present after a stats refresh, the selection is
preserved even if status changes. A disabled/removed selected device triggers
the same fallback.

## 6. Page projections

### Home

For the selected device only:

- overall status, public identity status, and last seen;
- Hardware and SMART;
- Hermes profile summary;
- Lucky summary;
- Docker running/total summary.

### Docker

For the selected device only:

- running/total;
- container list;
- domain status/error/staleness;
- collection/update time.

### Lucky

For the selected device only:

- service status and version;
- bounded/redacted address summary;
- DDNS, web service, port-forwarding, and certificate summaries.

An unconfigured Lucky integration is `not_configured`; it never falls through
to another device's Lucky data. Missing/invalid data uses the selected device's
own empty/error view.

## 7. Identity and privacy display

The UI may display the public identity state (`matched`, `missing_fqdn`,
`fqdn_mismatch`, or `unknown`) as a concise status. It does not display:

- tokens, credential IDs, or authentication mapping;
- authorization outcomes or detailed security audit messages;
- full internal addresses;
- raw FQDN by default;
- raw Client configuration;
- unbounded collector errors/raw responses.

Expected/reported FQDN fields are nullable in stats and are not required for
selection or routing.

## 8. Accessibility and responsive behavior

- desktop buttons and mobile select share a programmatic label;
- active device and status are not conveyed by color alone;
- keyboard focus is visible and selection works without a pointer;
- status changes use an appropriate polite live region without repeated noise;
- selector is horizontally scrollable or collapses before labels become
  unreadable;
- long names are bounded and ellipsized while the full safe label remains
  accessible.

## 9. Fetch and timer invariants

The following are hard test assertions:

- initial load makes one stats request;
- device change makes zero stats requests;
- primary page change makes zero stats requests;
- manual refresh makes exactly one request;
- only one automatic refresh timer exists;
- device/page changes do not replace that timer;
- one returned document serves all pages/devices;
- no WebSocket/SSE/direct collector API is added.

## 10. Frontend test cases

Fixtures cover at least online, degraded, stale, offline, never-seen, disabled,
removed, identity mismatch, and `not_configured` devices. Tests cover:

- desktop buttons and mobile select;
- default, URL, localStorage, and stable-order selection;
- invalid/duplicate/encoded device parameters;
- legacy hashes without `device`;
- selection persistence through stats refresh;
- fallback after removal/disable;
- Home/Docker/Lucky isolation between two distinct devices;
- offline and never-seen visibility;
- fetch/timer invariants;
- XSS payloads in every label/ID/error boundary;
- invalid device IDs never entering DOM or localStorage.

All current single-device fixtures remain valid through stats normalization.
The implemented dashboard uses safe DOM text binding for device labels/status,
keeps one `currentStats`, one fetch path, and one interval, and performs
device/page switches entirely against the cached document.
