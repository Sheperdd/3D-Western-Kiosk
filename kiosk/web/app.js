const displayNumber = new URLSearchParams(window.location.search).get("display");
const element = (id) => document.getElementById(id);

const states = {
  STARTING: {
    tone: "busy", icon: "wait", label: "Please wait", title: "Starting kiosk",
    message: "Please wait while the kiosk gets ready.",
  },
  IDLE: {
    tone: "ready", icon: "card", label: "Ready when you are",
    title: "Tap your card to check in or out",
    message: "Hold your student card over the readers until this screen says you can remove it.",
    next: "One card at a time. Use your own student card.",
  },
  REARMING: {
    tone: "busy", icon: "wait", label: "Please wait", title: "Getting ready for the next card",
    message: "Please wait before presenting another card.",
  },
  CHECKING: {
    tone: "busy", icon: "wait", label: "Card read", title: "Checking your card",
    message: "You can remove your card now. Please wait.",
  },
  OFFLINE: {
    tone: "unavailable", icon: "alert", label: "Temporarily unavailable",
    title: "Kiosk temporarily unavailable",
    message: "We can't connect to the access service. Please try later or contact the makerspace team.",
    next: "Please wait for the ready screen before presenting your card.",
  },
  READER_ERROR: {
    tone: "unavailable", icon: "alert", label: "Temporarily unavailable",
    title: "Card reader unavailable",
    message: "We can't read cards right now. Please contact the makerspace team.",
    next: "Please wait for the ready screen before presenting your card.",
  },
};

// The gatekeeper's message replaces `message` when it sends one; the backend owns that wording.
// `success` means "show access details", so check-out leaves it off.
const results = {
  CHECKED_IN: {
    tone: "success", icon: "check", label: "Checked in", title: "You're checked in",
    message: "Welcome to the makerspace.", success: true,
    next: "Remove your card. Follow each machine's operating instructions; access is checked again at the machine.",
  },
  CHECKED_OUT: {
    tone: "success", icon: "check", label: "Checked out", title: "You're checked out",
    message: "Thanks for visiting the makerspace.",
    next: "Remove your card. Tap again to check back in.",
  },
  DENIED: {
    tone: "attention", icon: "help", label: "Next step", title: "We couldn't check you in",
    message: "Contact the makerspace team for help.",
  },
  // A repeat tap within the debounce: the gatekeeper repeats its previous answer.
  IGNORED_DUPLICATE: {
    tone: "attention", icon: "card", label: "Card already read", title: "We already have your tap",
    message: "Your previous tap was recorded.",
  },
  READ_AGAIN: {
    tone: "attention", icon: "card", label: "Please try again", title: "Let's try your card again",
    message: "We couldn't read your card completely.",
  },
  // Never claim either way: the tap may or may not have landed.
  UNREACHABLE: {
    tone: "attention", icon: "card", label: "Please try again", title: "Couldn't reach the system",
    message: "Tap again when the ready screen returns. If this repeats, contact the makerspace team.",
  },
  NOT_SET_UP: {
    tone: "unavailable", icon: "alert", label: "Please ask for help", title: "Kiosk not set up",
    message: "Please contact the makerspace team.",
  },
};

const qrCodes = {
  UNKNOWN_STUDENT: "Create an account",
  ORIENTATION_REQUIRED: "Orientation",
};

const publicStatuses = {
  STARTING: {
    tone: "busy", icon: "wait", title: "Starting up — please wait",
    message: "The kiosk is getting ready.",
  },
  WAITING: {
    tone: "ready", icon: "card", title: "Ready for the next student",
    message: "Present your student card and follow the other screen.",
  },
  "IN USE": {
    tone: "busy", icon: "wait", title: "In use — please wait",
    message: "Give the person checking in or out space. Wait for the ready message.",
  },
  UNAVAILABLE: {
    tone: "unavailable", icon: "alert", title: "Kiosk temporarily unavailable",
    message: "Please contact the makerspace team if you need help.",
  },
};

const unavailable = {
  tone: "unavailable", icon: "alert", label: "Display unavailable",
  title: "Display information unavailable",
  message: "We can't show the kiosk status right now. Please contact the makerspace team.",
  next: "Please wait for the ready screen before presenting your card.",
};
const connectionLost = {
  ...unavailable, title: "Display connection lost",
  message: "We can't reach the kiosk. Please wait while the display reconnects.",
};
let lastView = "";

function render(view) {
  // Polls repeat the same payload; avoid re-announcing it or restarting the indicator.
  const key = JSON.stringify(view);
  if (key === lastView) return;
  lastView = key;
  document.body.dataset.tone = view.tone;

  if (displayNumber === "2") {
    element("public-status").textContent = view.title;
    element("public-message").textContent = view.message;
    element("general-icon").setAttribute("href", `#icon-${view.icon}`);
    return;
  }

  element("eyebrow").textContent = view.label;
  element("screen").textContent = view.title;
  element("message").textContent = view.message;
  element("student-icon").setAttribute("href", `#icon-${view.icon}`);
  element("access-details").hidden = !view.success;
  element("notices").textContent = view.notices || "";
  element("notices").hidden = !view.notices;
  element("qr-panel").hidden = !view.qr;
  element("qr-title").textContent = view.qr || "";
  element("next-step").textContent = view.next || "This screen updates automatically.";
}

function renderPayload(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    render(unavailable);
    return;
  }
  // Shown only when the kiosk says so: wrongly claiming "no real access changes" is the worse error.
  element("demo-badge").hidden = data.demo !== true;

  if (displayNumber === "2") {
    const status = data.status;
    render(typeof status === "string" && Object.hasOwn(publicStatuses, status)
      ? publicStatuses[status] : unavailable);
    return;
  }

  const text = (value) => value === null || typeof value === "string";
  if (typeof data.state !== "string" || !text(data.result) || !text(data.reason)
      || !text(data.message) || !Array.isArray(data.notices)
      || !data.notices.every((notice) => typeof notice === "string")) {
    render(unavailable);
    return;
  }

  if (data.state === "RESULT") {
    if (!Object.hasOwn(results, data.result)) {
      render(unavailable);
      return;
    }
    const result = results[data.result];
    render({
      next: "Remove your card. Please wait for the ready screen before another scan.",
      ...result,
      message: data.message || result.message,
      notices: data.notices.join("\n"),
      // Keyed on reason, so a repeated denial (IGNORED_DUPLICATE) shows its QR again.
      qr: Object.hasOwn(qrCodes, data.reason) ? qrCodes[data.reason] : "",
    });
    return;
  }

  render(Object.hasOwn(states, data.state) ? states[data.state] : unavailable);
}

async function loadDisplay() {
  try {
    const response = await fetch(`/api/display/${displayNumber}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) throw new Error(`Display request failed: ${response.status}`);
    renderPayload(await response.json());
  } catch {
    render(connectionLost);
  } finally {
    setTimeout(loadDisplay, 250);
  }
}

if (displayNumber === "1" || displayNumber === "2") {
  document.title = `3D Western · ${displayNumber === "1" ? "Student check-in" : "Makerspace guide"}`;
  element("student-view").hidden = displayNumber === "2";
  element("general-view").hidden = displayNumber === "1";
  render(displayNumber === "2" ? publicStatuses.STARTING : states.STARTING);
  loadDisplay();
} else {
  render({
    ...unavailable, title: "Choose a display",
    message: "Open this page with ?display=1 for student check-in or ?display=2 for the makerspace guide.",
    next: "Ask the person setting up the kiosk to select a display.",
  });
}
