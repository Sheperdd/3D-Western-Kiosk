const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const web = path.join(__dirname, "../kiosk/web");
const script = readFileSync(path.join(web, "app.js"), "utf8");
const html = readFileSync(path.join(web, "index.html"), "utf8");

function display(number = "1") {
  let writes = 0;
  const nodes = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(([, id]) => {
    let text = "";
    return [id, {
      hidden: true,
      get textContent() { return text; },
      set textContent(value) { text = value; writes++; },
      setAttribute(name, value) { this[name] = value; },
    }];
  }));
  const timers = [];
  const requests = [];
  const context = vm.createContext({
    URLSearchParams, AbortSignal,
    window: { location: { search: `?display=${number}` } },
    document: { body: { dataset: {} }, getElementById: (id) => nodes[id] },
    fetch: (url, options) => {
      requests.push({ url, options });
      return new Promise(() => {});
    },
    setTimeout: (callback, delay) => timers.push({ callback, delay }),
  });
  vm.runInContext(script, context);
  return { context, nodes, timers, requests, writes: () => writes };
}

const stateHeadings = {
  STARTING: "Starting kiosk",
  IDLE: "Tap your card to check in or out",
  REARMING: "Getting ready for the next card",
  ACTIVATING: "Checking your card",
  AWAITING_IDENTITY: "Checking your card details",
  REGISTERING: "Setting up your card",
  OFFLINE: "Kiosk temporarily unavailable",
  READER_ERROR: "Card reader unavailable",
  OUTCOME_UNKNOWN: "Result not confirmed",
};

test("every controller state has student instructions and clears result details", () => {
  const { context, nodes } = display();
  for (const [state, heading] of Object.entries(stateHeadings)) {
    context.renderPayload({ state: "RESULT", outcome: "REGISTERED_AND_ACTIVE" });
    context.renderPayload({ state, outcome: null });
    assert.equal(nodes.screen.textContent, heading);
    assert.equal(nodes["access-details"].hidden, true);
    assert.equal(nodes["qr-panel"].hidden, true);
  }
  assert.match(nodes["next-step"].textContent, /Don't scan again yet/);
});

const results = [
  ["REGISTERED_AND_ACTIVE", "You're checked in", true, ""],
  ["CHECKED_OUT", "You're checked out", false, ""],
  ["REPLACED_AND_ACTIVE", "Replacement card activated", true, ""],
  ["UNKNOWN_STUDENT", "Create your makerspace account", false, "Create an account"],
  ["MISSING_INDUCTION", "General induction required", false, "General induction"],
  ["DENIED", "Unable to activate your visit", false, ""],
  ["UID_CONFLICT", "This card needs assistance", false, ""],
  ["READ_AGAIN", "Let's try your card again", false, ""],
  ["SESSION_EXPIRED", "We couldn't complete this attempt", false, ""],
];

test("all final outcomes render, with training only on success and honest QR placeholders", () => {
  const { context, nodes } = display();
  for (const [outcome, heading, success, qr] of results) {
    context.renderPayload({ state: "RESULT", outcome });
    assert.equal(nodes.screen.textContent, heading);
    assert.equal(nodes["access-details"].hidden, !success);
    assert.equal(nodes["qr-panel"].hidden, !qr);
    assert.equal(nodes["qr-title"].textContent, qr);
    assert.match(nodes.message.textContent, /[Rr]emove/);
  }
  context.renderPayload({ state: "RESULT", outcome: "CHECKED_OUT" });
  assert.equal(nodes.eyebrow.textContent, "Checked out");
  assert.equal(context.document.body.dataset.tone, "success");
  assert.match(html, /Training level unavailable/);
  assert.match(html, /Machine access details unavailable/);
  assert.match(html, /Signup link not available in this demo/);
});

test("unknown or malformed payloads clear success without showing raw data", () => {
  const { context, nodes } = display();
  for (const data of [null, {}, [], "IDLE", { state: "IDLE" },
    { state: "RESULT", outcome: null }, { state: "RESULT", outcome: ["REGISTERED_AND_ACTIVE"] },
    { state: "RESULT", outcome: "UNREGISTERED" }, { state: "RESULT", outcome: "constructor" },
    { state: "<script>secret</script>", outcome: null }, { state: ["IDLE"], outcome: null }]) {
    context.renderPayload({ state: "RESULT", outcome: "REGISTERED_AND_ACTIVE" });
    context.renderPayload(data);
    assert.equal(nodes.screen.textContent, "Display information unavailable");
    assert.equal(nodes["access-details"].hidden, true);
  }
});

test("public display only renders availability, ignoring private fields", () => {
  const { context, nodes } = display("2");
  for (const [status, heading] of [
    ["STARTING", "Starting up — please wait"],
    ["WAITING", "Ready for the next student"],
    ["IN USE", "In use — please wait"],
    ["UNAVAILABLE", "Kiosk temporarily unavailable"],
  ]) {
    context.renderPayload({ status, outcome: "secret student data" });
    assert.equal(nodes["public-status"].textContent, heading);
    assert.equal(nodes["student-view"].hidden, true);
    assert.equal(nodes["general-view"].hidden, false);
    assert.ok(!Object.values(nodes).some((node) => node.textContent.includes("secret")));
  }
  for (const data of [null, {}, { status: ["WAITING"] }, { status: "constructor" },
    { status: "secret student data" }, { state: "RESULT", outcome: "REGISTERED_AND_ACTIVE" }]) {
    context.renderPayload(data);
    assert.equal(nodes["public-status"].textContent, "Display information unavailable");
  }
});

test("unchanged polling does not rewrite live regions or schedule result transitions", () => {
  const ui = display();
  const payload = { state: "RESULT", outcome: "REGISTERED_AND_ACTIVE" };
  ui.context.renderPayload(payload);
  const writes = ui.writes();
  ui.context.renderPayload(payload);
  assert.equal(ui.writes(), writes);
  assert.equal(ui.timers.length, 0);
  assert.equal(ui.nodes.screen.textContent, "You're checked in");
});

test("network, HTTP and JSON errors clear old results; polling recovers on both displays", async () => {
  for (const number of ["1", "2"]) {
    const { context, nodes, timers, requests } = display(number);
    const heading = number === "1" ? nodes.screen : nodes["public-status"];
    assert.equal(requests[0].url, `/api/display/${number}`);
    assert.equal(requests[0].options.cache, "no-store");
    assert.ok(requests[0].options.signal instanceof AbortSignal);
    const good = number === "1"
      ? { state: "RESULT", outcome: "REGISTERED_AND_ACTIVE" }
      : { status: "WAITING" };
    for (const fail of [
      async () => { throw new Error("network down"); },
      async () => ({ ok: false, status: 503 }),
      async () => ({ ok: true, json: async () => { throw new SyntaxError("bad JSON"); } }),
    ]) {
      context.renderPayload(good);
      context.fetch = fail;
      await context.loadDisplay();
      assert.equal(heading.textContent, "Display connection lost");
      assert.equal(nodes["access-details"].hidden, true);
      const retry = timers.pop();
      assert.equal(retry.delay, 250);
      context.fetch = async () => ({ ok: true, json: async () => good });
      await retry.callback();
      assert.equal(heading.textContent, number === "1" ? "You're checked in" : "Ready for the next student");
      assert.equal(timers.pop().delay, 250);
    }
  }
});

test("invalid display selection does not poll", () => {
  for (const number of ["", "3", "constructor"]) {
    const { nodes, requests, timers } = display(number);
    assert.equal(nodes.screen.textContent, "Choose a display");
    assert.equal(requests.length, 0);
    assert.equal(timers.length, 0);
  }
});
