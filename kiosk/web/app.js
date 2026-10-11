console.log("Kiosk app.js loaded");

const params = new URLSearchParams(window.location.search);
const displayNumber = params.get("display");

const screenElement = document.getElementById("screen");
const labelsElement = document.getElementById("labels");

async function loadDisplay() {
  if (displayNumber != "1" && displayNumber != "2") {
    screenElement.textContent = "INVALID DISPLAY";
    labelsElement.textContent = "";
    console.error("Invalid display number:", displayNumber);
    return;
  }

  try {
    const response = await fetch(`/api/display/${displayNumber}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    screenElement.textContent = data.screen;
    labelsElement.textContent = data.labels.join(" • ");
  } catch (error) {
    screenElement.textContent = "DISPLAY CONNECTION LOST";
    labelsElement.textContent = "";
    console.error("Error fetching display data:", error);
  } finally {
    setTimeout(loadDisplay, 250);
  }
}

loadDisplay();
