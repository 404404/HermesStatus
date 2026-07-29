"use strict";

// Stage A contract skeleton only. It does not import or modify production UI.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..", "..");

function fixture(name) {
  return JSON.parse(
    fs.readFileSync(
      path.join(root, "testdata", "multi_device", "valid", name),
      "utf8",
    ),
  );
}

function normalizeContractStats(document) {
  assert.equal(document.schema_version, 2);
  assert.equal(Object.hasOwn(document, "devices"), false);
  assert.ok(Array.isArray(document.servers));
  const ids = new Set();
  for (const server of document.servers) {
    assert.match(server.device_id, /^[a-z0-9][a-z0-9._-]{0,62}$/);
    assert.equal(ids.has(server.device_id), false);
    ids.add(server.device_id);
    assert.equal(server.expected_fqdn, null);
    assert.equal(server.reported_fqdn, null);
  }
  return {
    defaultDeviceId: document.default_device_id,
    servers: document.servers,
  };
}

function parseRouteContract(hash) {
  const raw = String(hash || "").replace(/^#/, "");
  const [pagePart, query = ""] = raw.split("?", 2);
  const page = new Set(["home", "docker", "lucky"]).has(pagePart)
    ? pagePart
    : "home";
  const params = new URLSearchParams(query);
  const values = params.getAll("device");
  const deviceId =
    values.length === 1 && /^[a-z0-9][a-z0-9._-]{0,62}$/.test(values[0])
      ? values[0]
      : null;
  return { page, deviceId };
}

test("synthetic single and four-device stats fixtures normalize without devices[]", () => {
  const single = normalizeContractStats(fixture("stats-v2-single.json"));
  const four = normalizeContractStats(fixture("stats-v2-four.json"));
  assert.equal(single.servers.length, 1);
  assert.equal(four.servers.length, 4);
  assert.ok(four.servers.some((server) => server.status === "never_seen"));
  assert.ok(four.servers.some((server) => server.status === "offline"));
  assert.ok(four.servers.some((server) => server.status === "disabled"));
});

test("route parser skeleton accepts legacy hashes and one validated device", () => {
  assert.deepEqual(parseRouteContract("#home"), {
    page: "home",
    deviceId: null,
  });
  assert.deepEqual(parseRouteContract("#docker?device=device-alpha"), {
    page: "docker",
    deviceId: "device-alpha",
  });
  assert.deepEqual(
    parseRouteContract("#lucky?device=device-alpha&device=device-beta"),
    { page: "lucky", deviceId: null },
  );
  assert.deepEqual(parseRouteContract("#home?device=%3Cscript%3E"), {
    page: "home",
    deviceId: null,
  });
});
