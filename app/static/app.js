(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);

  const editor = $("#source");
  const lineNumbers = $("#line-numbers");
  const sourceFile = $("#source-file");
  const problem = $("#problem");
  const stdin = $("#stdin");
  const testcases = $("#testcases");
  const filename = $("#filename");
  const lineCount = $("#line-count");
  const charCount = $("#char-count");
  const toast = $("#toast");
  const helpDialog = $("#help-dialog");
  const evaluateButton = $("#evaluate-btn");

  let toastTimer;

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 2800);
  }

  function updateEditorStats() {
    if (!editor) return;

    const lines = editor.value.split("\n").length;

    if (lineNumbers) {
      lineNumbers.textContent = Array.from(
        { length: lines },
        (_, index) => index + 1
      ).join("\n");
    }

    if (lineCount) {
      lineCount.textContent = `${lines} ${lines === 1 ? "line" : "lines"}`;
    }

    if (charCount) {
      charCount.textContent =
        `${editor.value.length} ${editor.value.length === 1 ? "character" : "characters"}`;
    }
  }

  function loadExample() {
    if (!editor) return;

    problem.value =
      "Read an integer n followed by n integers. Print the maximum value. Assume n is between 1 and 1000.";

    editor.value = `#include <stdio.h>

int main(void) {
    int n;
    if (scanf("%d", &n) != 1 || n < 1 || n > 1000) {
        return 1;
    }

    int value;
    int maximum;

    if (scanf("%d", &maximum) != 1) {
        return 1;
    }

    for (int i = 1; i < n; i++) {
        if (scanf("%d", &value) != 1) {
            return 1;
        }
        if (value > maximum) {
            maximum = value;
        }
    }

    printf("%d\\n", maximum);
    return 0;
}`;

    if (stdin) stdin.value = "5\n12 7 19 3 10";
    if (testcases) {
      testcases.value =
        "Input: 5\\n12 7 19 3 10\nExpected: 19\n\nInput: 3\\n-8 -2 -15\nExpected: -2";
    }

    if (filename) filename.textContent = "main.c";
    updateEditorStats();
    showToast("Example loaded. Review the code before using it.");
  }

  if (editor) {
    editor.addEventListener("input", updateEditorStats);

    editor.addEventListener("scroll", () => {
      if (lineNumbers) lineNumbers.scrollTop = editor.scrollTop;
    });

    updateEditorStats();
  }

  $("#load-example")?.addEventListener("click", loadExample);

  sourceFile?.addEventListener("change", () => {
    const file = sourceFile.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".c")) {
      showToast("Please choose a .c source file.");
      sourceFile.value = "";
      return;
    }

    if (file.size > 256 * 1024) {
      showToast("The source file must be 256 KB or smaller.");
      sourceFile.value = "";
      return;
    }

    const reader = new FileReader();

    reader.onload = () => {
      editor.value = String(reader.result ?? "");
      if (filename) filename.textContent = file.name;
      updateEditorStats();
      showToast(`Loaded ${file.name}. No code was uploaded to the server.`);
    };

    reader.onerror = () => showToast("Could not read that file.");
    reader.readAsText(file);
  });

  $("#help-btn")?.addEventListener("click", () => {
    if (helpDialog?.showModal) helpDialog.showModal();
  });

  helpDialog?.addEventListener("click", (event) => {
    if (event.target === helpDialog) helpDialog.close();
  });

  evaluateButton?.addEventListener("click", () => {
    showToast("Evaluation is not available yet. Secure execution is not enabled.");
  });

  async function checkHealth() {
    const serviceStatus = $("#service-status");
    const healthCheck = $("#health-check");
    const healthDetail = $("#health-detail");
    const healthState = $("#health-state");
    const footerStatus = $("#footer-status");

    try {
      const response = await fetch("/health", {
        headers: { Accept: "application/json" },
        cache: "no-store"
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      const healthy = data.status === "ok";

      if (serviceStatus) serviceStatus.textContent = healthy ? "Service online" : "Service issue";
      if (healthCheck) healthCheck.textContent = healthy ? "✓" : "!";
      if (healthDetail) healthDetail.textContent = healthy ? "API responded successfully" : "API returned an unhealthy status";
      if (healthState) healthState.textContent = healthy ? "ONLINE" : "CHECK";
      if (footerStatus) footerStatus.textContent = healthy ? "API connected" : "API issue";

      if (evaluateButton) {
        evaluateButton.disabled = true;
        evaluateButton.title = "Evaluation is disabled until secure execution is implemented.";
      }
    } catch (error) {
      if (serviceStatus) serviceStatus.textContent = "Service unavailable";
      if (healthCheck) healthCheck.textContent = "!";
      if (healthDetail) healthDetail.textContent = "Could not reach /health";
      if (healthState) healthState.textContent = "OFFLINE";
      if (footerStatus) footerStatus.textContent = "API disconnected";
    }
  }

  checkHealth();
})();
