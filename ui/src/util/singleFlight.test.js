import test from "node:test";
import assert from "node:assert/strict";

import { createSingleFlight } from "./singleFlight.js";

test("deduplicates concurrent work for the same key", async () => {
  const flight = createSingleFlight();
  let calls = 0;
  let release;
  const pending = new Promise((resolve) => {
    release = resolve;
  });
  const task = async () => {
    calls += 1;
    await pending;
    return "value";
  };

  const first = flight.run("project-1", task);
  const second = flight.run("project-1", task);
  release();

  assert.equal(first, second);
  assert.equal(await first, "value");
  assert.equal(calls, 1);
  assert.equal(flight.isRunning(), false);
});

test("starting a different key aborts the previous task", async () => {
  const flight = createSingleFlight();
  let firstSignal;
  const first = flight.run("project-1", async (signal) => {
    firstSignal = signal;
    await new Promise((resolve) => signal.addEventListener("abort", resolve));
    return "aborted";
  });
  await Promise.resolve();

  const second = flight.run("project-2", async () => "current");

  assert.equal(firstSignal.aborted, true);
  assert.equal(await first, "aborted");
  assert.equal(await second, "current");
});

test("failed work clears the flight so it can be retried", async () => {
  const flight = createSingleFlight();

  await assert.rejects(
    flight.run("project-1", async () => {
      throw new Error("failed");
    }),
    /failed/
  );
  assert.equal(flight.isRunning("project-1"), false);
  assert.equal(
    await flight.run("project-1", async () => "recovered"),
    "recovered"
  );
});

test("abort signals and clears active work", async () => {
  const flight = createSingleFlight();
  let signal;
  const pending = flight.run("project-1", async (currentSignal) => {
    signal = currentSignal;
    await new Promise((resolve) =>
      currentSignal.addEventListener("abort", resolve)
    );
  });
  await Promise.resolve();

  flight.abort();

  assert.equal(signal.aborted, true);
  assert.equal(flight.isRunning(), false);
  await pending;
});

test("reports running state by key and tolerates idle abort", async () => {
  const flight = createSingleFlight();
  let release;
  const pending = flight.run(
    "project-1",
    () => new Promise((resolve) => {
      release = resolve;
    })
  );
  await Promise.resolve();

  assert.equal(flight.isRunning(), true);
  assert.equal(flight.isRunning("project-1"), true);
  assert.equal(flight.isRunning("project-2"), false);
  release();
  await pending;
  flight.abort();
  assert.equal(flight.isRunning(), false);
});