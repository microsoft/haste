import test from "node:test";
import assert from "node:assert/strict";

import { buildBrowserStorageUrl } from "./blobUrl.js";

const sas = "?sv=2024-11-04&sig=secret-signature#fragment";
const blobUrl = `https://account.blob.core.windows.net/data/project/model/preview.jpeg${sas}`;

test("managed-identity proxy removes SAS and fragment", () => {
  const result = buildBrowserStorageUrl(
    blobUrl,
    "/api/haste/storage/get-artifacts",
    "https://haste.example/project/123"
  );

  assert.equal(
    result,
    "https://haste.example/api/haste/storage/get-artifacts/data/project/model/preview.jpeg"
  );
});

test("local Azurite endpoint preserves SAS required by the emulator", () => {
  const result = buildBrowserStorageUrl(
    `http://azurite:10000/devstoreaccount1/data/preview.jpeg${sas}`,
    "http://192.0.2.10:10000",
    "http://192.0.2.10:4280/project/123"
  );

  assert.equal(
    result,
    "http://192.0.2.10:10000/devstoreaccount1/data/preview.jpeg?sv=2024-11-04&sig=secret-signature"
  );
});

test("rejects untrusted storage origins", () => {
  assert.equal(
    buildBrowserStorageUrl(
      "https://attacker.example/data/project/model/file.jpeg",
      "/api/haste/storage/get-artifacts",
      "https://haste.example/"
    ),
    null
  );
});

test("rejects credentials and non-HTTP protocols", () => {
  assert.equal(
    buildBrowserStorageUrl(
      "https://user:password@account.blob.core.windows.net/data/project/model/file.jpeg",
      "/api/haste/storage/get-artifacts",
      "https://haste.example/"
    ),
    null
  );
  assert.equal(
    buildBrowserStorageUrl(
      "javascript://account.blob.core.windows.net/data/project/model/file.jpeg",
      "/api/haste/storage/get-artifacts",
      "https://haste.example/"
    ),
    null
  );
});

test("rejects paths that do not match the APIM operation contract", () => {
  assert.equal(
    buildBrowserStorageUrl(
      "https://account.blob.core.windows.net/data/project/file.jpeg",
      "/api/haste/storage/get-artifacts",
      "https://haste.example/"
    ),
    null
  );
});