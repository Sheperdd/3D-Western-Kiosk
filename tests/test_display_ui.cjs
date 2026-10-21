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

// The /api/display/1 payload as kiosk/__main__.py builds it.
const shown = (state, result = null, extra = {}) =>
  ({ state, result, reason: null, message: null, notices: [], ...extra });
const checkedIn = shown("RESULT", "CHECKED_IN", { message: "Welcome, Sam.", notices: ["Refresher due."] });

const stateHeadings = {
  STARTING: "Starting kiosk",
  IDLE: "Tap your card to check in or out",
  REARMING: "Getting ready for the next card",
  CHECKING: "Checking your card",
  OFFLINE: "Kiosk temporarily unavailable",
  READER_ERROR: "Card reader unavailable",
};

test("every controller state has student instructions and clears result details", () => {
  const { context, nodes } = display();
  for (const [state, heading] of Object.entries(stateHeadings)) {
    context.renderPayload(checkedIn);
    context.renderPayload(shown(state));
    assert.equal(nodes.screen.textContent, heading);
    assert.equal(nodes["access-details"].hidden, true);
    assert.equal(nodes["qr-panel"].hidden, true);
    assert.equal(nodes.notices.hidden, true);
  }
});

const resultHeadings = [
  ["CHECKED_IN", "You're checked in", true],
  ["CHECKED_OUT", "You're checked out", false],
  ["DENIED", "We couldn't check you in", false],
  ["IGNORED_DUPLICATE", "We already have your tap", false],
  ["READ_AGAIN", "Let's try your card again", false],
  ["UNREACHABLE", "Couldn't reach the system", false],
  ["NOT_SET_UP", "Kiosk not set up", false],
];

test("every result renders, with access details only on check-in and honest placeholders", () => {
  const { context, nodes } = display();
  for (const [result, heading, success] of resultHeadings) {
    context.renderPayload(shown("RESULT", result));
    assert.equal(nodes.screen.textContent, heading);
    assert.equal(nodes["access-details"].hidden, !success);
    assert.equal(nodes["qr-panel"].hidden, true);
    assert.ok(nodes.message.textContent, "local fallback when the gatekeeper sends no message");
    assert.match(nodes["next-step"].textContent, /Remove your card/);
  }
  context.renderPayload(shown("RESULT", "CHECKED_OUT"));
  assert.equal(nodes.eyebrow.textContent, "Checked out");
  assert.equal(context.document.body.dataset.tone, "success");
  context.renderPayload(shown("RESULT", "DENIED"));
  assert.equal(context.document.body.dataset.tone, "attention");
  assert.match(html, /Training level unavailable/);
  assert.match(html, /Machine access details unavailable/);
  assert.match(html, /QR link not set up yet/);
});

test("the gatekeeper's message and notices are shown as given, as text", () => {
  const { context, nodes } = display();
  context.renderPayload(shown("RESULT", "CHECKED_IN", {
    message: "Welcome, Sam.", notices: ["Laser Cutter: refresher due.", "<b>not markup</b>"],
  }));
  assert.equal(nodes.message.textContent, "Welcome, Sam.");
  assert.equal(nodes.notices.textContent, "Laser Cutter: refresher due.\n<b>not markup</b>");
  assert.equal(nodes.notices.hidden, false);
  context.renderPayload(shown("RESULT", "CHECKED_OUT"));
  assert.equal(nodes.message.textContent, "Thanks for visiting the makerspace.");
  assert.equal(nodes.notices.hidden, true);
});

test("QR codes follow the reason, including a repeated denial", () => {
  const { context, nodes } = display();
  for (const [result, reason, qr] of [
    ["DENIED", "UNKNOWN_STUDENT", "Create an account"],
    ["DENIED", "ORIENTATION_REQUIRED", "Orientation"],
    ["IGNORED_DUPLICATE", "UNKNOWN_STUDENT", "Create an account"],
    ["DENIED", "ORIENTATION_NOT_CONFIGURED", ""],
    ["DENIED", "BRAND_NEW_CODE", ""],
    ["DENIED", "constructor", ""],
    ["READ_AGAIN", "Incomplete scan: student number missing.", ""],
  ]) {
    context.renderPayload(shown("RESULT", result, { reason, message: "From the gatekeeper." }));
    assert.equal(nodes["qr-panel"].hidden, !qr);
    assert.equal(nodes["qr-title"].textContent, qr);
    assert.equal(nodes.message.textContent, "From the gatekeeper.");
  }
});

test("unknown or malformed payloads clear success without showing raw data", () => {
  const { context, nodes } = display();
  const denied = shown("RESULT", "DENIED");
  for (const data of [null, {}, [], "IDLE", { state: "IDLE" },
    { state: "RESULT", outcome: "CHECKED_IN" }, shown("RESULT"), shown("RESULT", ["CHECKED_IN"]),
    shown("RESULT", "UNREGISTERED"), shown("RESULT", "constructor"),
    shown("<script>secret</script>"), { ...shown("IDLE"), state: ["IDLE"] },
    { ...denied, message: 5 }, { ...denied, reason: {} }, { ...denied, notices: "secret" },
    { ...denied, notices: [1] }]) {
    context.renderPayload(checkedIn);
    context.renderPayload(data);
    assert.equal(nodes.screen.textContent, "Display information unavailable");
    assert.equal(nodes["access-details"].hidden, true);
    assert.equal(nodes.notices.hidden, true);
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
    context.renderPayload({ status, message: "secret student data", notices: ["secret"] });
    assert.equal(nodes["public-status"].textContent, heading);
    assert.equal(nodes["student-view"].hidden, true);
    assert.equal(nodes["general-view"].hidden, false);
    assert.ok(!Object.values(nodes).some((node) => node.textContent.includes("secret")));
  }
  for (const data of [null, {}, { status: ["WAITING"] }, { status: "constructor" },
    { status: "secret student data" }, checkedIn]) {
    context.renderPayload(data);
    assert.equal(nodes["public-status"].textContent, "Display information unavailable");
  }
});

test("unchanged polling does not rewrite live regions or schedule result transitions", () => {
  const ui = display();
  ui.context.renderPayload(checkedIn);
  const writes = ui.writes();
  ui.context.renderPayload(checkedIn);
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
    const good = number === "1" ? checkedIn : { status: "WAITING" };
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

test("the demo badge shows only when the kiosk says it is a demo", () => {
  assert.match(html, /id="demo-badge" class="demo" hidden/);  // Hidden until the first poll.
  for (const number of ["1", "2"]) {
    const { context, nodes } = display(number);
    const payload = number === "1" ? checkedIn : { status: "WAITING" };
    context.renderPayload({ ...payload, demo: true });
    assert.equal(nodes["demo-badge"].hidden, false);
    for (const demo of [false, undefined, "true", 1]) {
      context.renderPayload({ ...payload, demo });
      assert.equal(nodes["demo-badge"].hidden, true);
    }
  }
});
