const displayNumber = new URLSearchParams(window.location.search).get("display");
const element = (id) => document.getElementById(id);

const states = {
  STARTING: {
    tone: "busy", icon: "wait", label: "Please wait", title: "Starting kiosk",
    message: "Please wait while the kiosk gets ready.",
  },
  IDLE: {
    tone: "ready", icon: "card", label: "Ready when you are",
    title: "Activate your makerspace visit",
    message: "Hold your student card over the readers until this screen says you can remove it.",
    next: "One card at a time. Use your own student card.",
  },
  ACTIVATING: {
    tone: "busy", icon: "wait", label: "Card read", title: "Checking your access",
    message: "You can remove your card now. Please wait while we check your visit.",
  },
  AWAITING_IDENTITY: {
    tone: "busy", icon: "wait", label: "Card read", title: "Checking your card details",
    message: "You can remove your card. Please wait.",
    next: "Keep this screen in view. You do not need to scan again.",
  },
  REGISTERING: {
    tone: "busy", icon: "wait", label: "Please wait", title: "Setting up your card",
    message: "You can remove your card. Please wait while we finish setting up your visit.",
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
  OUTCOME_UNKNOWN: {
    tone: "unavailable", icon: "help", label: "Please ask for help", title: "Result not confirmed",
    message: "Remove your card. We couldn't confirm whether your visit was activated.",
    next: "Contact the makerspace team. Don't scan again yet.",
  },
};

const outcomes = {
  ACTIVATED: {
    title: "Your visit is active",
    message: "Remove your card. You're checked in for your makerspace visit.", success: true,
  },
  ALREADY_ACTIVE: {
    title: "Your visit is already active",
    message: "Remove your card. No further check-in is needed.", success: true,
  },
  REGISTERED_AND_ACTIVE: {
    title: "Card registered. Visit active.",
    message: "Remove your card. Your student card is ready for future check-ins.", success: true,
  },
  REPLACED_AND_ACTIVE: {
    title: "Replacement card activated",
    message: "Remove your card. Your previous card no longer works for makerspace access.", success: true,
  },
  UNKNOWN_STUDENT: {
    title: "Create your makerspace account",
    message: "Remove your card. Sign up for an account, then return and present your card again.",
    qr: "Create an account",
  },
  MISSING_INDUCTION: {
    title: "General induction required",
    message: "Remove your card. Complete general induction, then return after your training has been recorded.",
    qr: "General induction",
  },
  DENIED: {
    title: "Unable to activate your visit",
    message: "Remove your card. Contact the makerspace team for help.",
  },
  UID_CONFLICT: {
    title: "This card needs assistance",
    message: "Remove your card. Contact the makerspace team to resolve the card registration.",
  },
  READ_AGAIN: {
    title: "Let's try your card again",
    message: "We couldn't read your card completely. Remove it and wait for the ready screen before trying again.",
    retry: true,
  },
  SESSION_EXPIRED: {
    title: "We couldn't complete this attempt",
    message: "Remove your card. Wait for the ready screen, then try again. If this repeats, contact the makerspace team.",
    retry: true,
  },
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
    message: "Give the person checking in space. Wait for the ready message.",
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
  element("qr-panel").hidden = !view.qr;
  element("qr-title").textContent = view.qr || "";
  element("next-step").textContent = view.next || "This screen updates automatically.";
}

function renderPayload(data) {
  if (!data || typeof data.screen !== "string" || !Array.isArray(data.labels)
      || !data.labels.every((label) => typeof label === "string")) {
    render(unavailable);
    return;
  }

  if (displayNumber === "2") {
    const status = data.labels[0];
    render(data.screen === "GENERAL INSTRUCTIONS" && Object.hasOwn(publicStatuses, status)
      ? publicStatuses[status] : unavailable);
    return;
  }

  if (data.screen === "RESULT") {
    const outcome = data.labels[0];
    if (!Object.hasOwn(outcomes, outcome)) {
      render(unavailable);
      return;
    }
    const result = outcomes[outcome];
    render({
      tone: result.success ? "success" : "attention",
      icon: result.success ? "check" : result.retry ? "card" : "help",
      label: result.success ? "Checked in" : result.retry ? "Please try again" : "Next step",
      next: result.success
        ? "Follow each machine's operating instructions. Access is checked again at the machine."
        : "Please wait for the ready screen before another scan.",
      ...result,
    });
    return;
  }

  render(Object.hasOwn(states, data.screen) ? states[data.screen] : unavailable);
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
