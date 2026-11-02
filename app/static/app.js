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
  const demoModeCheckbox = $("#demo-mode");
  const demoScenarioControl = $("#demo-scenario-control");

  function updateDemoScenarioVisibility() {
    if (demoScenarioControl) {
      demoScenarioControl.hidden = !Boolean(demoModeCheckbox?.checked);
    }
  }

  demoModeCheckbox?.addEventListener("change", updateDemoScenarioVisibility);
  updateDemoScenarioVisibility();

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

  const resultsPanel = $("#analysis-results");
  const resultsSummary = $("#analysis-summary");
  const resultsFindings = $("#analysis-findings");

  evaluateButton?.addEventListener("click", async () => {
    const source = editor?.value ?? "";
    const demoMode = Boolean($("#demo-mode")?.checked);

    // Never allow results from an earlier submission to appear current.
    currentDraft = null;
    resetWorkflowProgress();
    if (agent1Panel) agent1Panel.hidden = true;
    if (agent2Panel) agent2Panel.hidden = true;
    if (agent3Panel) agent3Panel.hidden = true;
    if (resultsFindings) resultsFindings.replaceChildren();
    const oldDemoResults = $("#demo-results");
    const oldDemoOutput = $("#demo-agent-results");
    if (oldDemoResults) oldDemoResults.hidden = true;
    if (oldDemoOutput) oldDemoOutput.replaceChildren();
    if (executionOutput) executionOutput.textContent = "";
    ["#agent3a-execution-output", "#agent3b-output", "#agent3b-execution-output",
      "#agent4-output", "#agent5-output", "#agent6-output", "#grading-output"]
      .forEach(selector => $(selector)?.replaceChildren());
    if (downloadReportButton) downloadReportButton.disabled = true;

    if (!demoMode && !source.trim()) {
      showToast("Paste or load C source code first.");
      editor?.focus();
      return;
    }

    if (!demoMode && new TextEncoder().encode(source).length > 256 * 1024) {
      showToast("Source must be 256 KiB or smaller.");
      return;
    }

    evaluateButton.disabled = true;
    document.body.classList.add("analysis-casting");
    evaluateButton.textContent = "Analyzing…";
    if (resultsPanel) resultsPanel.hidden = false;
    if (resultsSummary) resultsSummary.textContent = "Analyzing source patterns…";
    if (resultsFindings) resultsFindings.replaceChildren();

    try {
      if (demoMode) {
        if (!instructorAuthenticated) {
          showToast("Log in as instructor before starting Demo Mode.");
          return;
        }
        if (resultsSummary) {
          resultsSummary.textContent = "Demo Mode uses a server-selected scenario. Static checks run on its scenario source; your editor contents remain unchanged.";
        }
        await runAgent1Workflow();
        return;
      }

      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json"
        },
        body: JSON.stringify({ source })
      });

      const data = await response.json();
      if (!response.ok) {
        const detail = typeof data.detail === "string"
          ? data.detail
          : `Request failed (HTTP ${response.status}).`;
        throw new Error(detail);
      }

      const risks = data.source_risks ?? {};
      const complexity = data.complexity ?? {};
      if (resultsSummary) {
        resultsSummary.textContent =
          `${risks.count ?? 0} targeted safety concern(s). ${complexity.summary || complexity.time_complexity || "Complexity pattern could not be classified."} ` +
          "Compiler and syntax checks run before problem reconstruction; no program is executed here.";
      }

      const structure = complexity.program_structure || risks.metrics || {};
      if (resultsFindings) {
        const structureCard = document.createElement("article");
        structureCard.className = "static-analysis-summary-card";
        const structureTitle = document.createElement("h3"); structureTitle.textContent = "Program structure";
        const structureText = document.createElement("p");
        structureText.textContent = [
          `${structure.function_count ?? structure.function_names?.length ?? 0} function(s)`,
          `${structure.loop_count ?? complexity.loop_count ?? 0} loop(s)`,
          `${structure.recursive_functions?.length ?? 0} recursive function(s)`,
          `${structure.array_access_count ?? structure.indexed_access_count ?? 0} indexed access(es)`,
          `${structure.dynamic_allocation_count ?? 0} dynamic allocation(s)`
        ].join(" · ");
        structureCard.append(structureTitle, structureText);
        if (complexity.summary) {
          const estimate = document.createElement("p"); estimate.textContent = complexity.summary;
          structureCard.append(estimate);
        }
        const loopModels = complexity.loop_analysis || [];
        if (loopModels.length) {
          const list = document.createElement("ul"); list.className = "result-list";
          loopModels.slice(0, 6).forEach(loop => {
            const item = document.createElement("li");
            item.textContent = `Line ${loop.line}: ${loop.kind} (${loop.header}) — ${loop.model} growth${loop.bound ? ` to ${loop.bound}` : ""}`;
            list.append(item);
          });
          structureCard.append(list);
        }
        (complexity.recursive_analysis || []).slice(0, 3).forEach(item => {
          const note = document.createElement("p");
          note.textContent = `${item.function}: ${item.inference}; ${item.self_calls} self-call(s)${item.recursive_call_inside_loop ? " inside a loop" : ""}.`;
          structureCard.append(note);
        });
        resultsFindings.append(structureCard);
      }

      const findings = [
        ...(risks.findings ?? []).map(item => ({
          title: item.severity === "high" ? "Important safety concern" : "Safety concern to review",
          line: item.line,
          message: item.message,
          evidence: item.evidence
        })),
        ...(complexity.findings ?? []).map(item => ({
          title: "Complexity detail",
          line: item.line,
          message: item.message,
          evidence: item.evidence
        }))
      ];

      if (resultsFindings) {
        if (findings.length === 0) {
          const empty = document.createElement("p");
          empty.textContent = "No heuristic findings were detected. This does not prove the program is correct.";
          resultsFindings.append(empty);
        }

        for (const finding of findings.slice(0, 5)) {
          const card = document.createElement("article");
          card.style.cssText = "border-top: 1px solid var(--border, #303543); padding: 12px 0;";
          const heading = document.createElement("h3");
          heading.textContent = finding.title +
            (Number.isInteger(finding.line) ? ` (line ${finding.line})` : "");
          const message = document.createElement("p");
          message.textContent = finding.message ?? "";
          card.append(heading, message);

          if (finding.evidence) {
            const evidence = document.createElement("pre");
            evidence.textContent = finding.evidence;
            card.append(evidence);
          }
          resultsFindings.append(card);
        }

        const note = document.createElement("p"); note.className = "result-muted";
        note.textContent = findings.length > 5
          ? `${findings.length - 5} additional findings are summarized in the report.`
          : (risks.message || "Compiler diagnostics are heuristic; test every relevant path.");
        resultsFindings.append(note);
      }

      showToast("Static analysis completed successfully.");

      // Static analysis always runs first. Both modes use the same
      // authenticated agent workflow; the server selects the provider.
      if (instructorAuthenticated) {
        await runAgent1Workflow();
      } else {
        showToast("Static analysis complete. Log in as instructor before Submit to start the full evaluation workflow.");
      }
    } catch (error) {
      if (resultsSummary) resultsSummary.textContent =
        `Analysis failed: ${error.message || "Could not reach the API."}`;
      showToast("Could not analyze source. Please try again.");
    } finally {
      document.body.classList.remove("analysis-casting");
      evaluateButton.disabled = false;
      evaluateButton.textContent = "SUBMIT";
    }
  });


  // Instructor-only Agent 1 → approval → Agent 2 workflow.
  const instructorLoginButton = $("#instructor-login");
  const instructorLoginPanel = $("#instructor-login-panel");
  const instructorControls = $("#instructor-controls");
  const instructorUsernameInput = $("#instructor-username");
  const instructorPasswordInput = $("#instructor-password");
  const logoutButton = $("#instructor-logout");
  const agent1Panel = $("#agent1-result");
  const agent1Summary = $("#agent1-summary");
  const assignmentDraft = $("#assignment-draft");
  const questionsPanel = $("#clarifying-questions");
  const approveButton = $("#approve-assignment");
  const agent2Panel = $("#agent2-result");
  const referenceOutput = $("#reference-output");

  let currentDraft = null;
  let instructorAuthenticated = false;

  async function apiRequest(url, payload = {}) {
    const requestId = globalThis.crypto?.randomUUID?.() ||
      `ui-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-Request-ID": requestId
        },
        body: JSON.stringify(payload)
      });
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      const stage = url.includes("/api/ui/generate-tests") ? "Agent 3" : "workflow";
      throw new Error(
        `Connection to the server was interrupted (request ${requestId}). The server may still be processing; check its matching ${stage} logs before retrying.`
      );
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof data.detail === "string"
        ? data.detail
        : `Request failed (HTTP ${response.status}).`);
    }
    return data;
  }

  function displayLabel(value) {
    return String(value)
      .replace(/_/g, " ")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/\b\w/g, char => char.toUpperCase());
  }

  function renderStructured(container, value) {
    if (!container) return;
    container.replaceChildren();

    const sensitive = /token|secret|password|api.?key|credential/i;

    function renderValue(parent, key, item) {
      if (sensitive.test(key)) return;

      if (item === null || item === undefined) return;

      if (Array.isArray(item)) {
        const section = document.createElement("section");
        section.className = "result-section";
        const heading = document.createElement("h4");
        heading.textContent = displayLabel(key);
        section.append(heading);

        if (!item.length) {
          const empty = document.createElement("p");
          empty.className = "result-muted";
          empty.textContent = "None reported.";
          section.append(empty);
        } else {
          const list = document.createElement("ul");
          list.className = "result-list";
          item.forEach((entry, index) => {
            const li = document.createElement("li");
            if (entry && typeof entry === "object") {
              renderValue(li, `Item ${index + 1}`, entry);
            } else {
              li.textContent = String(entry);
            }
            list.append(li);
          });
          section.append(list);
        }
        parent.append(section);
        return;
      }

      if (typeof item === "object") {
        const section = document.createElement("section");
        section.className = "result-section";
        const heading = document.createElement("h4");
        heading.textContent = displayLabel(key);
        section.append(heading);

        Object.entries(item).forEach(([childKey, childValue]) => {
          renderValue(section, childKey, childValue);
        });
        parent.append(section);
        return;
      }

      const field = document.createElement("div");
      field.className = "result-field";

      const label = document.createElement("span");
      label.className = "result-field-label";
      label.textContent = displayLabel(key);

      const text = document.createElement("div");
      text.className = "result-field-value";

      const isCode = /^(code|source|implementation)$/i.test(key);
      if (isCode) {
        const pre = document.createElement("pre");
        pre.className = "result-code";
        pre.textContent = String(item);
        text.append(pre);
      } else {
        text.textContent = String(item);
      }

      field.append(label, text);
      parent.append(field);
    }

    if (value && typeof value === "object" && !Array.isArray(value)) {
      Object.entries(value).forEach(([key, item]) => {
        renderValue(container, key, item);
      });
    } else {
      renderValue(container, "Result", value);
    }
  }


  // Isolated built-in demo. Sends no user submission fields.
  function demoText(parent, label, value) {
    const row = document.createElement("div");
    row.className = "demo-result-row";
    const heading = document.createElement("strong");
    heading.textContent = label;
    const body = document.createElement("div");
    if (value == null) {
      body.textContent = "—";
    } else if (typeof value === "object") {
      renderStructured(body, { result: value });
    } else {
      body.textContent = String(value);
    }
    row.append(heading, body);
    parent.append(row);
    return row;
  }

  function demoCode(parent, label, source) {
    if (typeof source !== "string") return;
    const details = document.createElement("details");
    details.className = "demo-code-details";
    const summary = document.createElement("summary");
    summary.textContent = `View ${label} C source`;
    const pre = document.createElement("pre");
    pre.textContent = source;
    details.append(summary, pre);
    parent.append(details);
  }


  // Shared measured-runtime chart for both normal and demo workflows.
  function renderBenchmarkChart(parent, benchmark) {
    const observations = Array.isArray(benchmark?.chart_data)
      ? benchmark.chart_data.filter(point =>
          point &&
          ["student", "brute_force", "efficient"].includes(point.program) &&
          Number.isFinite(Number(point.input_size)) &&
          Number.isFinite(Number(point.runtime_seconds)) &&
          Number(point.input_size) >= 0 &&
          Number(point.runtime_seconds) >= 0
        )
      : [];
    const grouped = new Map();
    for (const point of observations) {
      const key = String(point.program) + ":" + Number(point.input_size);
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(Number(point.runtime_seconds));
    }
    const points = Array.from(grouped, ([key, values]) => {
      const [program, size] = key.split(":");
      const sorted = values.sort((a, b) => a - b);
      const middle = Math.floor(sorted.length / 2);
      const median = sorted.length % 2
        ? sorted[middle]
        : (sorted[middle - 1] + sorted[middle]) / 2;
      return { program, input_size: Number(size), runtime_seconds: median, sample_count: sorted.length };
    });

    const comparisons = Array.isArray(benchmark?.differential_comparisons)
      ? benchmark.differential_comparisons
      : [];

    const colors = {
      student: "#BC5A89",
      brute_force: "#568AB0",
      efficient: "#628B70"
    };
    const names = {
      student: "Student",
      brute_force: "Brute force",
      efficient: "Efficient"
    };

    const section = document.createElement("section");
    section.className = "runtime-chart";
    const heading = document.createElement("h4");
    heading.textContent = "Measured runtime — actual process observations";
    section.append(heading);

    const legend = document.createElement("div");
    legend.className = "runtime-chart-legend";

    for (const key of Object.keys(names)) {
      const item = document.createElement("span");
      item.className = "runtime-chart-legend-item";
      const swatch = document.createElement("span");
      swatch.className = "runtime-chart-swatch";
      swatch.style.backgroundColor = colors[key];
      const label = document.createElement("span");
      label.textContent = names[key];
      item.append(swatch, label);
      legend.append(item);
    }
    section.append(legend);

    if (!points.length) {
      const empty = document.createElement("p");
      empty.textContent = "No successful runtime measurements are available.";
      section.append(empty);
    } else {
      const NS = "http://www.w3.org/2000/svg";
      const svg = document.createElementNS(NS, "svg");
      svg.setAttribute("viewBox", "0 0 800 390");
      svg.setAttribute("role", "img");
      svg.setAttribute(
        "aria-label",
        "Line graph of measured runtime in milliseconds against actual input size"
      );
      svg.classList.add("runtime-chart-svg");

      const make = (tag, attrs, text) => {
        const node = document.createElementNS(NS, tag);
        Object.entries(attrs || {}).forEach(([key, value]) =>
          node.setAttribute(key, String(value))
        );
        if (text != null) node.textContent = text;
        return node;
      };

      const left = 78, right = 770, top = 24, bottom = 310;
      const width = right - left, height = bottom - top;
      const sizes = points.map(p => Number(p.input_size));
      const times = points.map(p => Math.max(Number(p.runtime_seconds) * 1000, 0.001));
      const minX = Math.min(...sizes), maxX = Math.max(...sizes);
      const minY = Math.min(...times), maxY = Math.max(...times);
      const logX = minX > 0 && maxX / minX >= 100;
      const logY = maxY / minY >= 10;
      const tx = value => logX ? Math.log10(Math.max(value, 1e-12)) : value;
      const ty = value => logY ? Math.log10(Math.max(value, 1e-12)) : value;
      const xMin = tx(minX), xMax = tx(maxX), yMin = ty(minY), yMax = ty(maxY);
      const unTx = value => logX ? 10 ** value : value;
      const unTy = value => logY ? 10 ** value : value;
      const x = value => xMax === xMin
        ? left + width / 2
        : left + ((tx(value) - xMin) / (xMax - xMin)) * width;
      const y = value => yMax === yMin
        ? bottom - height / 2
        : bottom - ((ty(Math.max(value, 0.001)) - yMin) / (yMax - yMin)) * height;
      const formatAxisValue = value =>
        value >= 10000 || (value > 0 && value < 0.01)
          ? value.toExponential(1)
          : Number(value.toPrecision(3)).toString();

      const scaleNote = document.createElement("p");
      scaleNote.className = "runtime-chart-note";
      const ladder = Array.isArray(benchmark?.prioritized_size_ladder)
        ? benchmark.prioritized_size_ladder : [];
      scaleNote.textContent =
        "Measured observations summarized by median for each input size (" + observations.length +
        " successful process measurements). Adaptive axes: input " + (logX ? "logarithmic" : "linear") +
        ", runtime " + (logY ? "logarithmic" : "linear") + "." +
        (ladder.length
          ? " The time cap prioritizes a geometric ladder of " + ladder.length +
            " generated sizes; the full generated test set is retained."
          : " No geometric size ladder was available in the generated inputs.");
      section.append(scaleNote);

      // Grid and Y-axis tick labels.
      for (let i = 0; i <= 4; i++) {
        const value = unTy(yMin + (yMax - yMin) * i / 4);
        const py = bottom - (i / 4) * height;
        svg.append(make("line", {
          x1: left, y1: py, x2: right, y2: py,
          stroke: "#ded6dc", "stroke-dasharray": "4 5"
        }));
        svg.append(make("text", {
          x: left - 12, y: py + 4, "text-anchor": "end",
          fill: "#625761", "font-size": 11
        }, formatAxisValue(value)));
      }

      svg.append(make("line", {
        x1: left, y1: top, x2: left, y2: bottom,
        stroke: "#625761", "stroke-width": 1.3
      }));
      svg.append(make("line", {
        x1: left, y1: bottom, x2: right, y2: bottom,
        stroke: "#625761", "stroke-width": 1.3
      }));

      // Nice numeric ticks: retain all plotted measurements, but never
      // print hundreds of overlapping input-size labels.
      const tickCount = 7;
      const xTicks = [];
      if (logX) {
        for (let i = 0; i < tickCount; i++) {
          xTicks.push(unTx(xMin + (xMax - xMin) * i / (tickCount - 1)));
        }
      } else {
        const niceStep = raw => {
          if (!(raw > 0)) return 1;
          const power = Math.pow(10, Math.floor(Math.log10(raw)));
          const fraction = raw / power;
          const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 :
                       fraction <= 5 ? 5 : 10;
          return nice * power;
        };
        const step = niceStep((maxX - minX) / (tickCount - 1));
        const firstTick = Math.ceil(minX / step) * step;
        for (let value = firstTick;
             value <= maxX + step * 1e-9 && xTicks.length < tickCount;
             value += step) xTicks.push(Number(value.toPrecision(12)));
      }
      if (!xTicks.length) xTicks.push(minX);
      xTicks.forEach(size => {
        const px = x(size);
        svg.append(make("line", {
          x1: px, y1: bottom, x2: px, y2: bottom + 5,
          stroke: "#625761"
        }));
        svg.append(make("text", {
          x: px, y: bottom + 20, "text-anchor": "middle",
          fill: "#625761", "font-size": 11
        }, formatAxisValue(size)));
      });

      svg.append(make("text", {
        x: (left + right) / 2, y: 370,
        "text-anchor": "middle", fill: "#403741",
        "font-size": 13, "font-weight": 600
      }, "Actual input size (n" + (logX ? ", logarithmic" : "") + ")"));

      svg.append(make("text", {
        x: 18, y: (top + bottom) / 2,
        transform: `rotate(-90 18 ${(top + bottom) / 2})`,
        "text-anchor": "middle", fill: "#403741",
        "font-size": 13, "font-weight": 600
      }, "Runtime (ms" + (logY ? ", logarithmic" : "") + ")"));

      for (const key of Object.keys(names)) {
        const series = points
          .filter(p => p.program === key)
          .sort((a, b) => Number(a.input_size) - Number(b.input_size));

        if (!series.length) continue;

        const path = series.map((point, index) =>
          `${index ? "L" : "M"} ${x(Number(point.input_size))} ${y(Number(point.runtime_seconds) * 1000)}`
        ).join(" ");

        svg.append(make("path", {
          d: path, fill: "none", stroke: colors[key],
          "stroke-width": 3, "stroke-linecap": "round",
          "stroke-linejoin": "round"
        }));

        series.forEach(point => {
          const px = x(Number(point.input_size));
          const py = y(Number(point.runtime_seconds) * 1000);
          const circle = make("circle", {
            cx: px, cy: py, r: 4.5, fill: colors[key],
            stroke: "#fff", "stroke-width": 1.5
          });
          circle.append(make("title", {},
            `${names[key]} · n=${point.input_size} · ${(Number(point.runtime_seconds) * 1000).toFixed(3)} ms median of ${point.sample_count} run(s)`
          ));
          svg.append(circle);
        });
      }

      section.append(svg);
    }

    // Failed executions are status markers, never zero-runtime chart points.
    const failures = [];
    for (const comparison of comparisons) {
      const outcomes = comparison?.outcomes || {};
      for (const key of Object.keys(names)) {
        const outcome = outcomes[key];
        if (outcome && outcome.execution_class !== "program_success") {
          failures.push({
            size: comparison.input_size,
            program: names[key],
            status: outcome.execution_class || "execution_failed"
          });
        }
      }
    }

    const statusHeading = document.createElement("h5");
    statusHeading.textContent = "Timeouts and unsuccessful executions";
    section.append(statusHeading);

    if (!failures.length) {
      const none = document.createElement("p");
      none.textContent = "No timeouts or unsuccessful executions recorded.";
      section.append(none);
    } else {
      const list = document.createElement("ul");
      list.className = "runtime-chart-failures";
      failures.slice(0, 5).forEach(item => {
        const row = document.createElement("li");
        row.textContent =
          `n=${item.size} · ${item.program} · ${item.status}`;
        list.append(row);
      });
      section.append(list);
      if (failures.length > 5) {
        const more = document.createElement("p");
        more.textContent = `${failures.length - 5} additional unsuccessful run(s) are included in the downloadable report.`;
        section.append(more);
      }
    }

    const note = document.createElement("p");
    note.className = "runtime-chart-note";
    note.textContent =
      "Process startup and sandbox overhead are included. These observations are measurements, not proof of Big-O complexity.";
    section.append(note);
    parent.append(section);
  }

  function stageText(parent, label, value) {
    if (!parent || value == null || value === "") return;
    const row = document.createElement("p");
    row.className = "agent-result-summary";
    const strong = document.createElement("strong");
    strong.textContent = `${label}: `;
    row.append(strong, document.createTextNode(String(value)));
    parent.append(row);
  }

  function renderDifferentialResults(parent, comparisons, label, maxExamples = 5) {
    if (!parent) return 0;
    parent.replaceChildren();
    const cases = Array.isArray(comparisons) ? comparisons : [];
    const issues = [];
    let referenceDisagreements = 0;
    let inconclusive = 0;
    let studentMismatches = 0;
    let possibleFormatOnlyMismatches = 0;

    for (const item of cases) {
      const outcomes = item?.outcomes || {};
      const student = outcomes.student || {};
      const brute = outcomes.brute_force || {};
      const efficient = outcomes.efficient || {};
      const ran = [student, brute, efficient].every(
        value => value.execution_class === "program_success"
      );
      let kind = "passed";
      if (!ran) {
        kind = "inconclusive";
        inconclusive += 1;
      } else {
        const studentOut = String(student.stdout ?? "").trim();
        const bruteOut = String(brute.stdout ?? "").trim();
        const efficientOut = String(efficient.stdout ?? "").trim();
        if (bruteOut !== efficientOut) {
          kind = "reference_disagreement";
          referenceDisagreements += 1;
        } else if (studentOut !== bruteOut) {
          kind = "student_mismatch";
          studentMismatches += 1;
          const finalToken = value => value.split(/\s+/).filter(Boolean).at(-1) || "";
          if (finalToken(studentOut) && finalToken(studentOut) === finalToken(bruteOut)) {
            possibleFormatOnlyMismatches += 1;
            kind = "possible_output_format_mismatch";
          }
        }
      }
      if (kind !== "passed") issues.push({ item, kind, outcomes });
    }

    stageText(parent, `${label} cases compared`, cases.length);
    stageText(parent, "Student differs from agreeing references", studentMismatches);
    if (possibleFormatOnlyMismatches) {
      stageText(parent, "Possible format-only differences (same final token)", possibleFormatOnlyMismatches);
    }
    stageText(parent, "Brute-force / efficient reference disagreements", referenceDisagreements);
    stageText(parent, "Inconclusive executions", inconclusive);
    if (!issues.length) {
      stageText(parent, "Result", cases.length
        ? "All completed comparisons agree; this is empirical evidence, not a proof."
        : "No comparable cases were completed.");
      return 0;
    }

    const heading = document.createElement("h4");
    heading.textContent = "Cases requiring review";
    parent.append(heading);
    const shown = Math.min(Math.max(0, maxExamples), issues.length);
    for (const { item, kind, outcomes } of issues.slice(0, shown)) {
      const card = document.createElement("article");
      card.className = "agent-failure-case";
      const title = document.createElement("h4");
      title.textContent = `Case ${item.case ?? "?"} · ${kind.replaceAll("_", " ")}`;
      const inputTitle = document.createElement("strong");
      inputTitle.textContent = "Input";
      const input = document.createElement("pre");
      input.textContent = String(item.input ?? "Input unavailable");
      card.append(title, inputTitle, input);
      const results = document.createElement("div");
      results.className = "agent-case-output";
      for (const [key, name] of [
        ["student", "Student"], ["brute_force", "Brute force"], ["efficient", "Efficient"]
      ]) {
        const outcome = outcomes[key] || {};
        const block = document.createElement("div");
        const nameNode = document.createElement("strong");
        const executionLabel = String(outcome.execution_class || "not run")
          .replaceAll("_", " ");
        nameNode.textContent = name + " · " + executionLabel;
        const output = document.createElement("pre");
        if (outcome.execution_class === "program_success") {
          output.textContent = String(outcome.stdout ?? "(empty output)");
        } else if (outcome.timeout_source === "shared_benchmark_budget") {
          output.textContent = "Stopped because the shared benchmark time budget expired.";
        } else if (outcome.execution_class === "not_executed_before_deadline") {
          output.textContent = "Not started before the shared benchmark deadline.";
        } else {
          output.textContent = String(outcome.stderr || "No output available.");
        }
        block.append(nameNode, output);
        results.append(block);
      }
      card.append(results);
      if (kind === "possible_output_format_mismatch") {
        const formatNote = document.createElement("p");
        formatNote.className = "result-muted";
        formatNote.textContent = "The final output token matches the brute-force output, but the complete stdout differs. Extra prompts or labels still violate the approved output contract and remain a mismatch.";
        card.append(formatNote);
      }
      parent.append(card);
    }
    if (issues.length > shown) {
      stageText(parent, "Additional cases", `${issues.length - shown} more are retained in the downloadable test file and full PDF report.`);
    }
    return shown;
  }

  function renderStructuredSummary(parent, value, heading) {
    if (!parent) return;
    parent.replaceChildren();
    if (!value || typeof value !== "object") {
      stageText(parent, "Status", "No result was returned.");
      return;
    }
    if (heading) {
      const title = document.createElement("h4");
      title.textContent = heading;
      parent.append(title);
    }
    const content = document.createElement("div");
    content.className = "structured-results";
    renderStructured(content, value);
    parent.append(content);
  }

  function renderAssignmentSummary(parent, data) {
    if (!parent) return;
    parent.replaceChildren();
    const spec = data?.assignment_spec || {};
    const addSection = (title, value) => {
      if (!value) return;
      const section = document.createElement("section");
      section.className = "result-section user-summary-section";
      const heading = document.createElement("h4"); heading.textContent = title;
      const body = document.createElement("p"); body.textContent = String(value);
      section.append(heading, body); parent.append(section);
    };
    addSection("Problem", spec.problem_statement || data?.candidates?.[0]?.problem_statement);
    addSection("Input", spec.input_format || data?.candidates?.[0]?.input_format);
    addSection("Output contract", spec.output_format || data?.candidates?.[0]?.output_format);
    const constraints = spec.constraints || data?.constraints;
    if (Array.isArray(constraints) && constraints.length) {
      const section = document.createElement("section");
      section.className = "result-section user-summary-section";
      const heading = document.createElement("h4"); heading.textContent = "Constraints";
      const list = document.createElement("ul"); list.className = "result-list";
      constraints.slice(0, 10).forEach(value => { const item = document.createElement("li"); item.textContent = String(value); list.append(item); });
      section.append(heading, list); parent.append(section);
    }
    const fields = spec.input_schema?.fields;
    if (Array.isArray(fields) && fields.length) {
      const section = document.createElement("section");
      section.className = "result-section user-summary-section";
      const heading = document.createElement("h4"); heading.textContent = "Generated input schema";
      const list = document.createElement("ul"); list.className = "result-list";
      fields.slice(0, 10).forEach(field => {
        const details = [];
        if (field.type) details.push(displayLabel(field.type));
        if (field.min !== undefined || field.max !== undefined) {
          details.push(`range ${field.min ?? "?"} to ${field.max ?? "?"}`);
        }
        if (field.length_from) details.push(`length from ${displayLabel(field.length_from)}`);
        const item = document.createElement("li");
        item.textContent = `${displayLabel(field.name)}${details.length ? ` · ${details.join(" · ")}` : ""}`;
        list.append(item);
      });
      if (spec.input_schema.size_field) {
        const scale = document.createElement("p");
        scale.textContent = `Workload size: ${displayLabel(spec.input_schema.size_field)}`;
        section.append(heading, list, scale);
      } else {
        section.append(heading, list);
      }
      parent.append(section);
    }
    if (!parent.childElementCount) stageText(parent, "Problem", "Review the problem statement and confirm the intended input and output before continuing.");
  }

  function renderReferenceSolutions(parent, references) {
    if (!parent) return;
    parent.replaceChildren();
    stageText(parent, "Agent 2 status", references?.status || "no_response");
    if (references?.message) stageText(parent, "Why it stopped", references.message);
    for (const [label, item] of [["Brute-force reference", references?.brute_force], ["Efficient reference", references?.efficient]]) {
      if (!item || typeof item !== "object") continue;
      const card = document.createElement("article"); card.className = "reference-solution-card";
      const title = document.createElement("h4"); title.textContent = label;
      const name = document.createElement("p"); name.className = "reference-solution-name"; name.textContent = item.algorithm || "Algorithm summary unavailable";
      card.append(title, name);
      const facts = document.createElement("dl"); facts.className = "reference-solution-facts";
      for (const [term, value] of [["Time", item.time_complexity], ["Space", item.space_complexity]]) { if (!value) continue; const dt = document.createElement("dt"); dt.textContent = term; const dd = document.createElement("dd"); dd.textContent = String(value); facts.append(dt, dd); }
      card.append(facts);
      if (typeof item.code === "string" && item.code.trim()) {
        const details = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = "View reference implementation";
        const pre = document.createElement("pre"); pre.className = "result-code"; const code = document.createElement("code"); code.textContent = item.code; pre.append(code); details.append(summary, pre); card.append(details);
      }
      parent.append(card);
    }
    stageText(parent, "Evidence note", "Reference outputs are checked empirically; agreement is not a formal proof of correctness.");
  }

  function renderDemoBenchmark(parent, benchmark) {
    renderBenchmarkChart(parent, benchmark);

    const comparisons = Array.isArray(benchmark.differential_comparisons)
      ? benchmark.differential_comparisons : [];
    const issues = comparisons.filter(item => item?.outputs_agree !== true);
    demoText(parent, "Inputs compared", comparisons.length);
    if (issues.length) demoText(parent, "Cases to review", issues.length);
  }

  function renderDemoAgent(key, agent) {
    const titles = {
      agent1: "AGENT 1 — PROBLEM RECONSTRUCTION",
      agent2: "AGENT 2 — THREE C IMPLEMENTATIONS",
      agent3a: "AGENT 3A — GENERATOR AND REAL BENCHMARK",
      agent3b: "AGENT 3B — EXECUTED EDGE CASES",
      agent4: "AGENT 4 — COMPLEXITY ANALYSIS",
      agent5: "AGENT 5 — MATHEMATICAL CORRECTNESS",
      agent6: "AGENT 6 — CODE QUALITY REVIEW"
    };

    const card = document.createElement("article");
    card.className = "demo-agent-card";
    const heading = document.createElement("h3");
    heading.textContent = titles[key] || key.toUpperCase();
    const label = document.createElement("p");
    label.className = "demo-real-label";
    label.textContent = "PREDEFINED DEMO DATA · REAL EXECUTION WHERE INDICATED";
    card.append(heading, label);

    if (key === "agent2") {
      for (const name of ["student", "brute_force", "efficient"]) {
        const item = agent[name] || {};
        const section = document.createElement("section");
        section.className = "demo-implementation";
        const h = document.createElement("h4");
        h.textContent = name.replace("_", " ").toUpperCase();
        section.append(h);
        demoText(section, "Time complexity", item.time_complexity);
        demoText(section, "Space complexity", item.space_complexity);
        demoCode(section, name, item.code);
        card.append(section);
      }
    } else if (key === "agent3a") {
      renderDemoBenchmark(card, agent.benchmark || {});
    } else if (key === "agent3b") {
      demoText(card, "Passed", `${agent.passed ?? 0} / ${agent.total ?? 0}`);
      const failures = (agent.cases || []).filter(item => item.passed !== true);
      demoText(card, "Failure examples shown", Math.min(5, failures.length));
      for (const item of failures.slice(0, 5)) {
        const section = document.createElement("section");
        section.className = "demo-edge-case";
        const h = document.createElement("h4");
        h.textContent = `${item.passed ? "✓" : "✗"} ${item.name}`;
        section.append(h);
        demoText(section, "Expected output", item.expected_output);
        demoText(section, "Actual output", item.actual_output);
        demoText(section, "Rationale", item.rationale);
        card.append(section);
      }
    } else {
      const details = document.createElement("div");
      details.className = "structured-results";
      if (key === "agent1") {
        renderAssignmentSummary(details, agent);
      } else if (key === "agent4") {
        renderAgent4(details, agent);
      } else if (key === "agent5") {
        renderAgent5(details, agent);
      } else if (key === "agent6") {
        renderAgent6(details, agent);
      }
      card.append(details);
    }
    return card;
  }

  async function runDemo() {
    const results = $("#demo-results");
    const notice = $("#demo-notice");
    const output = $("#demo-agent-results");
    if (!results || !output) return;

    evaluateButton.disabled = true;
    const originalLabel = evaluateButton.textContent;
    evaluateButton.textContent = "RUNNING DEMO…";
    results.hidden = false;
    output.replaceChildren();
    if (notice) {
      notice.textContent =
        "REAL LOCAL DEMO. Uses built-in Two Sum inputs and trusted C programs. " +
        "Your problem statement, source code, stdin and test cases are ignored. " +
        "No AI provider is called. GCC compilation, sandbox execution, edge-case " +
        "tests and benchmark timings are real.";
    }

    try {
      const response = await fetch("/api/ui/demo", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json"
        },
        body: JSON.stringify({ demo_mode: true })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(typeof data.detail === "string"
          ? data.detail : `Demo request failed (HTTP ${response.status}).`);
      }
      if (data.simulation !== false || !data.agents ||
          typeof data.agents !== "object") {
        throw new Error("The server did not return the expected real-demo payload.");
      }

      for (const key of [
        "agent1", "agent2", "agent3a", "agent3b",
        "agent4", "agent5", "agent6"
      ]) {
        if (!data.agents[key]) continue;
        output.append(renderDemoAgent(key, data.agents[key]));
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      showToast("Real demo completed. No submitted code or AI provider was used.");
    } catch (error) {
      const message = document.createElement("p");
      message.textContent = `Demo failed: ${error.message}`;
      output.append(message);
      showToast("Demo failed. Check the server output.");
    } finally {
      evaluateButton.disabled = false;
      evaluateButton.textContent = originalLabel;
    }
  }

  instructorLoginButton?.addEventListener("click", async () => {
    const username = instructorUsernameInput?.value.trim() ?? "";
    const password = instructorPasswordInput?.value ?? "";
    if (!username || !password) {
      showToast("Enter your instructor username and password.");
      return;
    }

    instructorLoginButton.disabled = true;
    instructorLoginButton.textContent = "[ signing in… ]";
    try {
      await apiRequest("/api/ui/login", { username, password });
      instructorAuthenticated = true;
      instructorPasswordInput.value = "";
      instructorLoginPanel.hidden = true;
      instructorControls.hidden = false;
      showToast("Instructor session active for 30 minutes.");
    } catch (error) {
      showToast(`Login failed: ${error.message}`);
    } finally {
      instructorLoginButton.disabled = false;
      instructorLoginButton.textContent = "[ instructor login ]";
    }
  });

  function renderPreflightCard(result) {
    if (!resultsFindings) return;
    resultsFindings.querySelector(".preflight-result-card")?.remove();
    const preflight = result?.preflight || {};
    const compilation = result?.compilation || {};
    const card = document.createElement("article");
    card.className = "preflight-result-card";
    const heading = document.createElement("h3"); heading.textContent = "Preflight before problem analysis";
    const checks = document.createElement("ul"); checks.className = "preflight-check-list";
    const add = (label, detail, passed) => {
      const item = document.createElement("li");
      const state = document.createElement("strong");
      state.textContent = passed ? "Passed" : "Needs attention";
      const text = document.createElement("span"); text.textContent = `${label} — ${detail}`;
      item.className = passed ? "preflight-check-pass" : "preflight-check-review";
      item.append(state, text); checks.append(item);
    };
    const sizeDetail = preflight.decision === "continue" ? "within configured limit" : (preflight.reasons?.[0] || "source validation did not pass");
    add("Source size", `${Number(preflight.source_bytes || 0).toLocaleString()} bytes; ${sizeDetail}`, preflight.decision === "continue");
    add("C syntax and compilation", compilation.status === "compiled" ? "GCC compiled the program before Agent 1 ran" : (compilation.message || compilation.status || "not checked"), compilation.status === "compiled");
    const diagnosticText = compilation.compiler_stderr || "";
    const diagnosticLines = diagnosticText.split("\n").filter(line => /(?:warning|error):/.test(line)).slice(0, 4);
    card.append(heading, checks);
    if (diagnosticLines.length) {
      const diagnostics = document.createElement("ul"); diagnostics.className = "preflight-diagnostics";
      diagnosticLines.forEach(line => { const item = document.createElement("li"); item.textContent = line.trim(); diagnostics.append(item); });
      card.append(diagnostics);
    }
    const note = document.createElement("p"); note.className = "result-muted";
    note.textContent = "Compilation checks syntax and emits static diagnostics; it does not run the submitted program or prove memory safety.";
    card.append(note);
    if (Array.isArray(preflight.reasons) && preflight.reasons.length) {
      const reason = document.createElement("p"); reason.textContent = preflight.reasons.join(" "); card.append(reason);
    }
    resultsFindings.prepend(card);
  }

  async function runAgent1Workflow() {
    if (!instructorAuthenticated) {
      showToast("Please log in as instructor first.");
      return;
    }

    const source = editor?.value ?? "";
    const demoMode = Boolean($("#demo-mode")?.checked);
    if (!demoMode && !source.trim()) {
      showToast("Add C source code before submitting.");
      editor?.focus();
      return;
    }

    resetWorkflowProgress();
    evaluateButton.textContent = "AGENT 1 WORKING…";
    agent1Panel.hidden = false;
    agent2Panel.hidden = true;
    approveButton.disabled = true;
    if (agent1Summary) agent1Summary.textContent = "Checking source size and compiling safely before Agent 1…";
    if (questionsPanel) questionsPanel.replaceChildren();

    let agent1Started = false;
    try {
      const preparationPayload = {
        source: demoMode ? "" : source,
        problem_statement: demoMode ? null : (problem?.value?.trim() || null),
        demo_mode: demoMode,
        demo_scenario_id: demoMode ? $("#demo-scenario")?.value : null
      };
      const preflightData = await apiRequest("/api/ui/preflight", preparationPayload);
      renderPreflightCard(preflightData);
      if (preflightData.preflight?.decision !== "continue" || preflightData.compilation?.status !== "compiled") {
        const error = new Error(preflightData.compilation?.message || preflightData.preflight?.reasons?.[0] || "Source validation or compilation failed.");
        error.preflightBlocked = true;
        throw error;
      }
      if (agent1Summary) agent1Summary.textContent = "Preflight passed. Starting problem reconstruction…";
      agent1Started = true;

      const data = await apiRequest("/api/ui/prepare", preparationPayload);

      currentDraft = data;
      renderPreflightCard(data);
      if (demoMode) {
        const risks = data.source_risks ?? {};
        const complexity = data.complexity_estimate ?? {};
        if (resultsSummary) {
          resultsSummary.textContent = `Static checks on ${data.demo_scenario_name}: ${risks.count ?? 0} heuristic risk finding(s). Estimated time: ${complexity.time_complexity ?? "unknown"}. No static finding is a correctness verdict.`;
        }
        if (resultsFindings) {
          const findings = [
            ...(risks.findings ?? []).map(item => ({title: "Potential source issue", line: item.line, message: item.message, evidence: item.evidence})),
            ...(complexity.findings ?? []).map(item => ({title: "Complexity signal", line: item.line, message: item.message, evidence: item.evidence}))
          ];
          if (!findings.length) {
            const note = document.createElement("p");
            note.textContent = "No heuristic findings were detected. This does not prove correctness.";
            resultsFindings.append(note);
          }
          for (const finding of findings.slice(0, 5)) {
            const card = document.createElement("article");
            const heading = document.createElement("h3");
            heading.textContent = finding.title + (Number.isInteger(finding.line) ? ` (line ${finding.line})` : "");
            const message = document.createElement("p");
            message.textContent = finding.message ?? "";
            card.append(heading, message);
            if (finding.evidence) {
              const evidence = document.createElement("pre");
              evidence.textContent = finding.evidence;
              card.append(evidence);
            }
            resultsFindings.append(card);
          }
          const note = document.createElement("p");
          note.className = "result-muted";
          note.textContent = findings.length > 5
            ? `${findings.length - 5} more findings are available in the report. Static analysis is heuristic.`
            : "Static analysis is heuristic and does not establish correctness.";
          resultsFindings.append(note);
        }
      }
      renderAssignmentSummary(assignmentDraft, data);

      if (agent1Summary) {
        agent1Summary.textContent =
          (data.assignment_spec ? "Problem reconstruction draft is ready for review." : "Problem details need review.") +
          (data.demo_scenario_name ? ` Demo scenario: ${data.demo_scenario_name}; AI responses are simulated.` : "");
      }

      const questions = data.clarifying_questions ?? [];
      if (questionsPanel) {
        const heading = document.createElement("h4");
        heading.textContent = "CLARIFYING QUESTIONS";
        questionsPanel.append(heading);
        if (!questions.length) {
          const note = document.createElement("p");
          const reconstructionStatus = data.reconstruction?.status;
          note.textContent = reconstructionStatus === "provider_error"
            ? "Agent 1 did not return a usable draft. No schema entry is required from you."
            : "No clarifying questions were returned. Review the generated I/O contract carefully.";
          questionsPanel.append(note);
        }
        for (const question of questions) {
          const item = document.createElement("p");
          item.textContent = typeof question === "string"
            ? question
            : String(question.question ?? question.text ?? question.prompt ?? "Please review this clarification.");
          questionsPanel.append(item);
        }
      }

      const schemaReady = Boolean(
        Array.isArray(data.assignment_spec?.input_schema?.fields) &&
        data.assignment_spec.input_schema.fields.length > 0
      );
      const ready =
        data.assignment_spec_status === "draft_requires_instructor_confirmation" &&
        data.assignment_spec &&
        schemaReady &&
        typeof data.assignment_spec_fingerprint === "string" &&
        typeof data.assignment_spec_draft_token === "string";
      const provisional = data.reconstruction?.status === "needs_clarification";

      approveButton.disabled = !ready;
      const reconstructionStatus = data.reconstruction?.status;
      const reconstructionMessage = data.reconstruction?.message || data.message;
      if (agent1Summary && ready && provisional) {
        agent1Summary.textContent =
          "Agent 1 generated a provisional problem and I/O contract. Review its assumptions; no schema entry is required from you.";
      } else if (agent1Summary && !ready) {
        if (reconstructionStatus === "provider_error" || data.status === "ai_unavailable") {
          agent1Summary.textContent = "Agent 1 could not complete the reconstruction" +
            (reconstructionMessage ? `: ${reconstructionMessage}` : ".") +
            " The schema is generated by Agent 1; it is not a user input.";
        } else if (reconstructionStatus === "needs_clarification") {
          agent1Summary.textContent =
            "Agent 1 could not safely infer one complete problem and I/O contract from the submitted code. The optional problem statement can help; do not enter a schema.";
        } else {
          agent1Summary.textContent = schemaReady
            ? "Agent 1 did not return one complete reviewable problem draft."
            : "Agent 1 did not return a valid structured input schema. The workflow paused before Agent 2; schema entry is not required from you.";
          if (data.assignment_spec_error) {
            agent1Summary.textContent += ` Details: ${data.assignment_spec_error}`;
          }
        }
      }
      showToast(ready
        ? (provisional
          ? "Agent 1 produced a provisional I/O contract for review."
          : "Agent 1 completed. Review its generated I/O contract.")
        : reconstructionStatus === "provider_error" || data.status === "ai_unavailable"
          ? "Agent 1 request failed; no schema was accepted."
          : "Agent 1 did not produce a complete I/O contract; no code was executed.");
    } catch (error) {
      currentDraft = null;
      if (agent1Summary) agent1Summary.textContent = !agent1Started ? `Preflight did not complete: ${error.message}` : `Agent 1 failed: ${error.message}`;
      showToast(`Preparation failed: ${error.message}`);
    }
  }

  approveButton?.addEventListener("click", async () => {
    if (!currentDraft?.assignment_spec || !currentDraft.assignment_spec_draft_token) {
      showToast("No valid draft is available for approval.");
      return;
    }

    const hasOpenQuestions = Boolean(currentDraft.reconstruction?.status === "needs_clarification");
    const confirmMessage = hasOpenQuestions
      ? "This is a provisional problem specification with open clarification(s) shown above. Approving it accepts those assumptions for reference generation. Correctness testing still requires a valid input format/schema. Continue?"
      : "You are approving this reconstructed problem specification. Agent 2 will then generate reference solutions. Continue?";
    const confirmed = window.confirm(confirmMessage);
    if (!confirmed) return;

    approveButton.disabled = true;
    approveButton.textContent = "[ confirming… ]";
    try {
      const confirmation = await apiRequest("/api/ui/confirm-assignment", {
        submission_id: currentDraft.submission_id,
        instructor_approved: true,
        accept_provisional_spec: hasOpenQuestions
      });

      if (agent1Summary) {
        agent1Summary.textContent = "Problem specification approved. Preparing the reference approaches…";
      }

      agent1Panel.hidden = true;
      if (referenceOutput) {
        referenceOutput.textContent = "Generating reference solutions…";
      }
      agent2Panel.hidden = false;

      const references = await apiRequest("/api/ui/generate-references", {
        submission_id: currentDraft.submission_id
      });

      currentDraft.references = references;
      renderReferenceSolutions(referenceOutput, references);
      const referencesReady = Boolean(
        references?.brute_force?.code?.trim() &&
        references?.efficient?.code?.trim()
      );
      agent2Panel.hidden = false;
      if (!referencesReady) {
        if (agent3Panel) agent3Panel.hidden = true;
        showToast(references?.message || "Agent 2 did not return both reference programs. Agent 3 is paused.");
        return;
      }
      configureAgent3SchemaMode();
      if (agent3Panel) agent3Panel.hidden = false;
      showToast(confirmation.assignment_spec?.input_schema
        ? "Agent 2 finished. Its references remain visible while Agent 3 is open."
        : "Agent 2 finished. Set Agent 3's input bounds; the references stay visible.");
    } catch (error) {
      if (referenceOutput) referenceOutput.textContent = `Reference generation failed: ${error.message}`;
      agent1Panel.hidden = false;
      agent2Panel.hidden = false;
      if (agent3Panel) agent3Panel.hidden = true;
      showToast(`Approval or reference generation failed: ${error.message}`);
    } finally {
      approveButton.disabled = false;
      approveButton.textContent = "[ confirm specification as instructor ]";
    }
  });


  const agent3Panel = $("#agent3-panel");
  const agent3Button = $("#agent3-generate");
  const agent3Output = $("#agent3-output");
  const agent3bOutput = $("#agent3b-output");
  const agent3aExecutionOutput = $("#agent3a-execution-output");
  const agent3bExecutionOutput = $("#agent3b-execution-output");
  const agent4Output = $("#agent4-output");
  const agent5Output = $("#agent5-output");
  const agent6Output = $("#agent6-output");
  const gradingOutput = $("#grading-output");
  const agent3SchemaSummary = $("#agent3-schema-summary");
  const agent3LegacyControls = [
    $("#agent3-token-count-control"),
    $("#agent3-minimum-control"),
    $("#agent3-maximum-control")
  ];

  function configureAgent3SchemaMode() {
    const schema = currentDraft?.assignment_spec?.input_schema;
    const structured = Boolean(
      schema && typeof schema === "object" &&
      Array.isArray(schema.fields) && schema.fields.length > 0
    );

    agent3LegacyControls.forEach(control => {
      if (control) control.hidden = true;
    });

    if (agent3SchemaSummary) {
      agent3SchemaSummary.hidden = !structured;
      agent3SchemaSummary.textContent = structured
        ? [
            "APPROVED INPUT FORMAT",
            ...schema.fields.map(field => {
              const details = [];
              if (field.type) details.push(String(field.type).replace(/_/g, " "));
              if (field.min !== undefined) details.push("minimum " + field.min);
              if (field.max !== undefined) details.push("maximum " + field.max);
              if (field.length_from) details.push("length determined by " + field.length_from);
              return "• " + displayLabel(field.name) +
                (details.length ? " — " + details.join(", ") : "");
            }),
            schema.size_field ? "Size field: " + displayLabel(schema.size_field) : ""
          ].filter(Boolean).join("\\n")
        : "";
    }
    return structured;
  }

  agent3Button?.addEventListener("click", async () => {
    if (!currentDraft?.submission_id || !instructorAuthenticated) {
      showToast("Instructor login and a prepared submission are required.");
      return;
    }

    const readNumber = id => Number($(id)?.value);
    const structuredMode = configureAgent3SchemaMode();
    const payload = {
      submission_id: currentDraft.submission_id,
      random_count: readNumber("#agent3-random-count"),
      adversarial_count: readNumber("#agent3-adversarial-count"),
      random_distribution: $("#agent3-distribution")?.value || "uniform"
    };

    if (!structuredMode) {
      showToast("Agent 1 must produce an approved input schema before tests can be generated.");
      return;
    }

    if (Object.values(payload).some(
      value => typeof value === "number" && !Number.isSafeInteger(value)
    )) {
      showToast("Enter valid whole numbers for all test settings.");
      return;
    }
    if (
      !structuredMode &&
      (payload.minimum > payload.maximum || payload.token_count < 1)
    ) {
      showToast("Check the legacy input token count and integer bounds.");
      return;
    }

    agent3aCard.hidden = false;
    agent3bCard.hidden = false;
    executionControls.hidden = false;
    agent4Card.hidden = true;
    agent5Card.hidden = true;
    agent6Card.hidden = true;
    gradingCard.hidden = true;
    downloadTestCasesButton.hidden = true;
    downloadReportButton.hidden = true;
    downloadReportButton.disabled = true;
    executeTestsButton.hidden = false;
    agent3Button.disabled = true;
    agent3Button.textContent = "[ generating tests… ]";
    if (agent3Output) agent3Output.textContent =
      "Agent 3A is generating and validating bounded inputs; Agent 3B and runtime comparisons follow. Test inputs are capped at 16 KiB each and 512 KiB total, regardless of larger legal schema bounds. This can take up to about two minutes. Keep this page open and do not submit the same run again.";
    try {
      const result = await apiRequest("/api/ui/generate-tests", payload);
      currentDraft.testPlans = result;
      currentDraft.executionResult = null;

      // Render a compact, human-readable Agent 3 result.
      // Generated inputs and nested case arrays belong in the ZIP, not the UI.
      agent3Output?.replaceChildren();

      const addText = (parent, tag, text, className) => {
        const element = document.createElement(tag);
        element.textContent = text;
        if (className) element.className = className;
        parent.append(element);
        return element;
      };

      const findValue = (obj, pattern, depth = 0) => {
        if (!obj || typeof obj !== "object" || depth > 6) return null;
        for (const [key, value] of Object.entries(obj)) {
          if (pattern.test(key) && value != null) return value;
        }
        for (const [key, value] of Object.entries(obj)) {
          if (Array.isArray(value)) continue;
          const found = findValue(value, pattern, depth + 1);
          if (found != null) return found;
        }
        return null;
      };

      const agent3a = result.agent3a || {};
      const generation = agent3a.generation || {};
      const localRandomPlan = result.random_tests || {};
      if (localRandomPlan.coverage_status === "partial" || localRandomPlan.status === "generator_error") {
        const localCount = Number(localRandomPlan.count || localRandomPlan.inputs?.length || 0);
        const requestedLocalCount = Number(localRandomPlan.requested_count || payload.random_count);
        stageText(agent3Output, "Bounded local sample",
          localRandomPlan.message || `${localCount} of ${requestedLocalCount} requested inputs fit the local per-case and batch byte limits.`);
      }
      const generatedCount = Array.isArray(generation.inputs)
        ? generation.inputs.length : 0;
      if (generation.requested_count) {
        const emitted = generation.returned_count ?? generatedCount;
        const rejected = Number(generation.rejected_count || 0);
        stageText(agent3Output, "Agent 3A coverage",
          `${generatedCount} valid unique cases of ${generation.requested_count} requested (${emitted} emitted${rejected ? `, ${rejected} rejected` : ""}; ${Number(generation.total_input_bytes || 0).toLocaleString()} input bytes).`);
        const firstReason = generation.rejected_cases?.[0]?.reason;
        if (firstReason) stageText(agent3Output, "First rejected case reason", firstReason);
      }
      stageText(agent3Output, "Agent 3A status",
        generation.coverage_status === "partial"
          ? `generated · partial coverage (${generatedCount}/${generation.requested_count})`
          : agent3a.status || generation.status || "not_run");
      if (agent3a.message || agent3a.reason || generation.message || generation.reason) {
        stageText(agent3Output, "Agent 3A note",
          agent3a.message || agent3a.reason || generation.message || generation.reason);
      }
      const edgeCases = Array.isArray(result.agent3b?.cases) ? result.agent3b.cases.length : 0;
      if (agent3bOutput) {
        agent3bOutput.replaceChildren();
        const edge = result.agent3b || {};
        stageText(agent3bOutput, "Agent 3B status", edge.status || "not_run");
        stageText(agent3bOutput, "Targeted edge cases", (edge.cases || []).length);
        stageText(agent3bOutput, "Agent 3B summary", edge.summary);
        if (edge.reason || edge.message) {
          stageText(agent3bOutput, "Note", edge.reason || edge.message);
        }
        if (result.demo_simulation_notice) {
          stageText(agent3bOutput, "Demo label", "Simulated AI proposal; validation and C execution are real.");
        }
      }
      if (agent3bExecutionOutput) {
        agent3bExecutionOutput.replaceChildren();
        stageText(agent3bExecutionOutput, "Execution", "Run the local execution step to compare these cases.");
      }

      // Download a plain-text copy of the same cases shown below.
      const download = document.createElement("button");
      download.type = "button";
      download.className = "secondary-button";
      download.textContent = `↓ Download test cases (.txt) — ${generatedCount} random cases`;
      download.disabled = generatedCount === 0 &&
        !(result.agent3b?.cases?.length);
      download.style.margin = "12px 0";
      download.addEventListener("click", () => downloadGeneratedTests(
        currentDraft?.testPlans || result,
        currentDraft?.executionResult || null
      ));
      agent3Output?.append(download);

      addText(agent3Output, "h3", "Test plan");
      addText(agent3Output, "p", `${generatedCount} random cases and ${edgeCases} targeted edge cases are ready for local execution.`);

      const benchmark = result.agent3a_benchmark || {};
      if (Array.isArray(benchmark.chart_data) && benchmark.chart_data.length) {
        addText(agent3Output, "p", `${benchmark.chart_data.length} successful runtime observations are plotted below.`);
      }

      const randomComparisons = (benchmark.differential_comparisons || []).map(item => ({
        ...item,
        input: generation.inputs?.[Number(item.case) - 1]?.input
      }));
      const randomDifferences = randomComparisons.filter(
        item => item.outputs_agree === false
      );
      const randomInconclusive = randomComparisons.filter(
        item => item.outputs_agree === null
      );
      const budgetSeconds = Number(benchmark.time_budget_seconds);
      if (Number.isFinite(budgetSeconds)) {
        stageText(agent3Output, "Benchmark time cap",
          `${budgetSeconds.toFixed(1)} seconds shared across the three programs (adaptive, capped at 10 seconds).`);
      }
      if (!randomDifferences.length) {
        renderBenchmarkChart(agent3Output, benchmark);
        if (randomInconclusive.length) {
          stageText(agent3Output, "Benchmark coverage",
            randomInconclusive.length + " case(s) were inconclusive or timed out. The graph shows successful measured runs only.");
        }
      } else {
        stageText(agent3Output, "Runtime graph",
          "Withheld because completed runs disagree on output. Resolve correctness differences before comparing performance.");
      }
      currentDraft.agent3aFailureExamples = renderDifferentialResults(
        agent3aExecutionOutput,
        randomComparisons,
        "Agent 3A random"
      );

      if (result.status === "generated") agent3Button.hidden = true;
      showToast(result.status === "generated"
        ? "Agent 3A generated and benchmarked the three implementations; Agent 3B edge cases are ready for execution."
        : "Test generation did not complete successfully.");
    } catch (error) {
      if (agent3Output) agent3Output.textContent = `Test generation failed: ${error.message}`;
      showToast(`Agent 3 failed: ${error.message}`);
    } finally {
      agent3Button.disabled = false;
      agent3Button.textContent = "[ generate random + adversarial tests ]";
    }
  });


  function buildGeneratedTestsText(result, execution = null) {
    const lines = [
      "AUTOGRADER — GENERATED TEST CASES",
      "=".repeat(44),
      ""
    ];

    const inputs = result.agent3a?.generation?.inputs || [];
    const comparisons = result.agent3a_benchmark?.differential_comparisons || [];
    const byCase = new Map(
      comparisons.map(item => [Number(item.case), item])
    );

    lines.push("AGENT 3A — RANDOM TEST CASES", "-".repeat(44), "");

    inputs.forEach((test, index) => {
      const brute = byCase.get(index + 1)?.outcomes?.brute_force || {};
      const comparison = byCase.get(index + 1) || {};
      const efficient = comparison.outcomes?.efficient || {};
      const student = comparison.outcomes?.student || {};
      const output =
        brute.execution_class === "program_success" &&
        typeof brute.stdout === "string"
          ? brute.stdout.trimEnd()
          : "Not available — brute-force reference did not complete.";

      lines.push(
        `CASE ${(index + 1).toString().padStart(3, "0")}`,
        "INPUT:",
        String(test.input ?? ""),
        "",
        "OUTPUT:",
        output,
        `EFFICIENT CROSS-CHECK: ${efficient.execution_class === "program_success" ? String(efficient.stdout ?? "").trimEnd() : "Unavailable"}`,
        `STUDENT OUTPUT: ${student.execution_class === "program_success" ? String(student.stdout ?? "").trimEnd() : "Unavailable"}`,
        comparison.outputs_agree === true
          ? "All three implementations agreed on this case."
          : "Reference agreement or student correctness needs review; see downloaded evidence.",
        "",
        ""
      );
    });

    const adversarial = result.agent3b?.cases || [];
    const edgeComparisons = execution?.agent3b_execution?.differential_comparisons || [];
    lines.push("AGENT 3B — ADVERSARIAL TEST CASES", "-".repeat(44), "");

    adversarial.forEach((test, index) => {
      const outcomes = edgeComparisons[index]?.outcomes || {};
      const brute = outcomes.brute_force || {};
      const efficient = outcomes.efficient || {};
      const expected = brute.execution_class === "program_success"
        ? String(brute.stdout ?? "")
        : "Not available — brute-force reference did not complete.";
      const oracleNote = brute.execution_class === "program_success" &&
        efficient.execution_class === "program_success" &&
        String(brute.stdout ?? "").trim() !== String(efficient.stdout ?? "").trim()
        ? "Reference disagreement: inspect both implementations before interpreting this case."
        : "Expected output uses the executed brute-force reference; it is not a formal certificate.";

      lines.push(
        `CASE ${(index + 1).toString().padStart(3, "0")}`,
        `NAME: ${test.name || "Adversarial case"}`,
        "INPUT:",
        String(test.input ?? ""),
        "",
        "BRUTE-FORCE OUTPUT:",
        expected.trimEnd(),
        `EFFICIENT OUTPUT: ${efficient.execution_class === "program_success" ? String(efficient.stdout ?? "").trimEnd() : "Not available"}`,
        `STUDENT OUTPUT: ${outcomes.student?.execution_class === "program_success" ? String(outcomes.student.stdout ?? "").trimEnd() : "Not available"}`,
        oracleNote,
        "",
        `RATIONALE: ${test.rationale || "Not provided."}`,
        `FAILURE HYPOTHESIS: ${test.failure_hypothesis || "Not provided."}`,
        ""
      );
    });

    if (!inputs.length && !adversarial.length) {
      lines.push("No generated test cases are available.");
    }

    return lines.join("\n");
  }

  function downloadGeneratedTests(result, execution = null) {
    const blob = new Blob(
      [buildGeneratedTestsText(result, execution)],
      { type: "text/plain;charset=utf-8" }
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "autograder-generated-test-cases.txt";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast("Test cases downloaded as a plain-text file.");
  }

  function renderComplexityCurve(parent, graph, label) {
    if (!parent || graph?.status !== "completed" || !Array.isArray(graph.points) || graph.points.length < 2) {
      stageText(parent, `${label} graph`, graph?.message || "No safe curve could be generated from this notation.");
      return;
    }
    const points = graph.points.filter(point =>
      Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y))
    );
    if (points.length < 2) return;
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 720 300");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${label} generic asymptotic growth curve`);
    svg.classList.add("runtime-chart-svg");
    const minX = Math.min(...points.map(point => Number(point.x)));
    const maxX = Math.max(...points.map(point => Number(point.x)));
    const ys = points.map(point => Number(point.y));
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const left = 68, right = 695, top = 24, bottom = 245;
    const x = value => maxX === minX ? (left + right) / 2
      : left + (Math.log(Number(value)) - Math.log(minX)) /
        (Math.log(maxX) - Math.log(minX)) * (right - left);
    const y = value => maxY === minY ? (top + bottom) / 2
      : bottom - (Number(value) - minY) / (maxY - minY) * (bottom - top);
    for (let index = 0; index <= 4; index++) {
      const py = top + (bottom - top) * index / 4;
      const line = document.createElementNS(NS, "line");
      line.setAttribute("x1", left); line.setAttribute("x2", right);
      line.setAttribute("y1", py); line.setAttribute("y2", py);
      line.setAttribute("stroke", "#ded6dc"); line.setAttribute("stroke-dasharray", "4 5");
      svg.append(line);
    }
    const make = (tag, attrs, text) => {
      const node = document.createElementNS(NS, tag);
      Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
      if (text != null) node.textContent = text;
      return node;
    };
    svg.append(make("line", { x1: left, y1: top, x2: left, y2: bottom, stroke: "#625761" }));
    svg.append(make("line", { x1: left, y1: bottom, x2: right, y2: bottom, stroke: "#625761" }));
    const path = points.map((point, index) =>
      `${index ? "L" : "M"} ${x(point.x)} ${y(point.y)}`
    ).join(" ");
    svg.append(make("path", { d: path, fill: "none", stroke: "#8b5483", "stroke-width": 3 }));
    points.forEach(point => svg.append(make("circle", {
      cx: x(point.x), cy: y(point.y), r: 3.5, fill: "#8b5483"
    })));
    svg.append(make("text", { x: (left + right) / 2, y: 282, "text-anchor": "middle", fill: "#403741", "font-size": 12 },
      graph.axis?.x_label || "Generic input scale n"));
    svg.append(make("text", { x: 18, y: 140, transform: "rotate(-90 18 140)", "text-anchor": "middle", fill: "#403741", "font-size": 12 },
      graph.axis?.y_label || "Representative growth"));
    const section = document.createElement("section");
    section.className = "runtime-chart";
    const title = document.createElement("h4");
    title.textContent = `${label} · ${graph.original_notation || "complexity expression"}`;
    section.append(title, svg);
    stageText(section, "Sampling", graph.sampling?.method || "Adaptive bounded sampling");
    if (Array.isArray(graph.approximations) && graph.approximations.length) {
      stageText(section, "Approximation used", graph.approximations.join("; "));
    }
    if (Array.isArray(graph.warnings) && graph.warnings.length) {
      stageText(section, "Numerical notes", graph.warnings.join("; "));
    }
    stageText(section, "Interpretation", "Generic asymptotic shape only; these axes are not measured input size and runtime.");
    parent.append(section);
  }

  function renderAgent4(parent, analysis) {
    if (!parent) return;
    parent.replaceChildren();
    const ai = analysis?.ai_analysis || analysis || {};
    // Keep machine status codes out of the learner-facing summary.
    stageText(parent, "Algorithm", ai.algorithm?.name);
    stageText(parent, "Input-size model", ai.algorithm?.input_size_model);
    const time = ai.time_complexity || {};
    stageText(parent, "Time · best / average / worst",
      [time.best_case, time.average_case, time.worst_case].map(item => item || "not distinguished").join(" / "));
    stageText(parent, "Time derivation", time.derivation);
    const space = ai.space_complexity || {};
    stageText(parent, "Space · auxiliary / total", [space.auxiliary, space.total].map(item => item || "unknown").join(" / "));
    stageText(parent, "Space derivation", space.derivation);
    // Confidence values are omitted because they are not calibrated guarantees.
    if (Array.isArray(ai.evidence) && ai.evidence.length) {
      const list = document.createElement("ul");
      list.className = "result-list";
      ai.evidence.slice(0, 4).forEach(item => {
        const li = document.createElement("li");
        li.textContent = `Lines ${item.line_start}–${item.line_end}: ${item.claim}`;
        list.append(li);
      });
      parent.append(list);
    }
    for (const [key, graph] of Object.entries(analysis?.complexity_graphs || {})) {
      renderComplexityCurve(parent, graph, displayLabel(key));
    }
    const notes = (ai.limitations || analysis?.limitations || []).slice(0, 2);
    if (notes.length) {
      const details = document.createElement("details");
      const summary = document.createElement("summary"); summary.textContent = "Analysis notes";
      const list = document.createElement("ul");
      notes.forEach(note => { const item = document.createElement("li"); item.textContent = note; list.append(item); });
      details.append(summary, list); parent.append(details);
    }
    if (analysis?.message || analysis?.reason || analysis?.provider_error?.message) {
      stageText(parent, "Details", analysis.message || analysis.reason || analysis.provider_error.message);
    }
  }

  function renderAgent5(parent, verification) {
    if (!parent) return;
    parent.replaceChildren();
    // The proof claim and reasoning are more useful than an internal status label.
    stageText(parent, "Theorem", verification?.theorem);
    stageText(parent, "Proof strategy", verification?.proof_strategy);
    const conditions = document.createElement("details");
    const conditionsTitle = document.createElement("summary"); conditionsTitle.textContent = "Proof conditions and assumptions";
    const conditionsList = document.createElement("ul");
    for (const [label, key] of [["Preconditions", "preconditions"], ["Postconditions", "postconditions"], ["Assumptions", "assumptions"]]) {
      const values = verification?.[key];
      if (!Array.isArray(values) || !values.length) continue;
      values.forEach(value => { const li = document.createElement("li"); li.textContent = `${label}: ${value}`; conditionsList.append(li); });
    }
    if (conditionsList.childElementCount) { conditions.append(conditionsTitle, conditionsList); parent.append(conditions); }
    const steps = verification?.proof_steps || [];
    if (steps.length) {
      const section = document.createElement("section");
      const title = document.createElement("h4"); title.textContent = "Proof steps"; section.append(title);
      steps.forEach((step, index) => {
        const card = document.createElement("article"); card.className = "agent-result-summary";
        const claim = document.createElement("strong"); claim.textContent = `${index + 1}. ${step.claim}`;
        const why = document.createElement("p"); why.textContent = step.justification;
        card.append(claim, why);
        if (step.equation) { const eq = document.createElement("pre"); eq.textContent = step.equation; card.append(eq); }
        section.append(card);
      });
      parent.append(section);
    }
    if (verification?.counterexample) {
      const card = document.createElement("article"); card.className = "agent-failure-case";
      const title = document.createElement("h4"); title.textContent = "Counterexample proposed by Agent 5";
      card.append(title);
      for (const [label, key] of [["Input", "input"], ["Expected behavior", "expected_behavior"], ["Observed or predicted behavior", "observed_or_predicted_behavior"], ["Explanation", "explanation"]]) stageText(card, label, verification.counterexample[key]);
      parent.append(card);
    }
    stageText(parent, "Conclusion", verification?.conclusion || verification?.message);
    const note = document.createElement("p");
    note.textContent = "AI proof sketch only. This result is not machine-checked formal verification.";
    parent.append(note);
  }

  function renderAgent6(parent, review) {
    if (!parent) return;
    parent.replaceChildren();
    stageText(parent, "Code review", review?.summary);
    for (const [label, values] of [["Strengths", (review?.strengths || []).slice(0, 3)]]) {
      if (!Array.isArray(values) || !values.length) continue;
      const title = document.createElement("h4"); title.textContent = label; parent.append(title);
      const list = document.createElement("ul");
      values.forEach(value => { const li = document.createElement("li"); li.textContent = String(value); list.append(li); });
      parent.append(list);
    }
    const ratings = review?.rubric_ratings || {};
    const ratingGrid = document.createElement("div"); ratingGrid.className = "rubric-rating-grid";
    for (const [name, item] of Object.entries(ratings)) {
      const card = document.createElement("article"); card.className = "rubric-rating";
      const title = document.createElement("h4"); title.textContent = displayLabel(name);
      const score = document.createElement("strong"); score.textContent = item?.rating == null ? "Not scored" : `${item.rating * 25} / 100`;
      const anchor = document.createElement("p"); anchor.textContent = item?.rationale || "Evidence rating unavailable.";
      card.append(title, score, anchor);
      (item?.evidence || []).slice(0, 2).forEach(ref => {
        const evidence = document.createElement("small"); evidence.textContent = `Line ${ref.line}: ${ref.quote}`; card.append(evidence);
      });
      ratingGrid.append(card);
    }
    if (ratingGrid.childElementCount) parent.append(ratingGrid);
    for (const finding of (review?.findings || []).slice(0, 5)) {
      const card = document.createElement("article"); card.className = "agent-failure-case";
      const title = document.createElement("h4"); title.textContent = `${finding.severity || "Finding"}: ${finding.title || finding.category || "Review item"}`;
      const body = document.createElement("p"); body.textContent = finding.description || "";
      card.append(title, body);
      stageText(card, "Evidence", finding.evidence);
      stageText(card, "Suggested improvement", finding.recommendation);
      parent.append(card);
    }
  }

  function renderGrade(parent, result) {
    if (!parent) return;
    parent.replaceChildren();
    const grade = result?.grading || {};
    const hero = document.createElement("div"); hero.className = "grade-score-hero";
    const band = document.createElement("div"); band.className = "grade-band"; band.textContent = grade.grade_band || "—";
    const score = document.createElement("div"); score.className = "grade-score-value";
    score.textContent = grade.score == null ? "Not gradeable" : `${grade.score} / ${grade.score_scale?.maximum ?? 100}`;
    const status = document.createElement("div"); status.className = "grade-status";
    status.textContent = grade.score == null ? "MORE EVIDENCE NEEDED" : "FINAL GRADE";
    hero.append(band, score, status); parent.append(hero);
    stageText(parent, "Interpretation", grade.message || "");
    const breakdown = grade.breakdown || {};
    const grid = document.createElement("div"); grid.className = "grade-metric-grid";
    for (const [name, item] of Object.entries(breakdown)) {
      const card = document.createElement("article"); card.className = "grade-metric";
      const heading = document.createElement("h4"); heading.textContent = displayLabel(name);
      const value = document.createElement("strong"); value.textContent = item.score == null ? "Not scored" : `${item.score} / 100`;
      const track = document.createElement("div"); track.className = "grade-meter";
      const fill = document.createElement("span"); fill.style.width = `${Math.max(0, Math.min(100, Number(item.score) || 0))}%`; track.append(fill);
      const detail = document.createElement("small"); detail.textContent = `${item.weight}% of grade${item.reason ? ` · ${item.reason}` : ""}`;
      card.append(heading, value, track, detail); grid.append(card);
    }
    if (grid.childElementCount) parent.append(grid);
    const fingerprint = grade.reproducibility?.fingerprint;
    if (fingerprint) {
      stageText(parent, "Reproducibility ID", fingerprint);
      stageText(parent, "Grading rules", grade.reproducibility.rules_version);
      const snapshotStatus = grade.reproducibility.grade_snapshot_status;
      stageText(parent, "Grade saved",
        snapshotStatus === "reused"
          ? "A previous matching grade was reused."
          : snapshotStatus === "saved"
            ? "The first complete grade was saved for matching future submissions."
            : "Not yet saved because the AI evidence is incomplete.");
    }
    const note = document.createElement("p"); note.className = "result-muted";
    note.textContent = "Timeouts and infrastructure errors are inconclusive and do not count as wrong answers.";
    parent.append(note);
  }

  function renderExecutionSummary(container, result) {
    if (container) {
      container.replaceChildren();
      const tests = result?.test_evaluation || {};
      stageText(container, "Test results", `${tests.passed ?? 0} passed · ${tests.failed ?? 0} failed · ${tests.inconclusive ?? 0} inconclusive`);
      stageText(container, "Interpretation", "Runtime and output observations are empirical evidence; they do not by themselves prove correctness.");
      const memory = result?.memory_safety;
      if (memory && typeof memory === "object") {
        const card = document.createElement("section"); card.className = "memory-diagnostic-card";
        const heading = document.createElement("h3"); heading.textContent = "Memory checks · one representative test input";
        const note = document.createElement("p");
        note.textContent = "AddressSanitizer/UBSan and Valgrind inspect only the executed path; a clean run does not establish general memory safety.";
        const grid = document.createElement("div"); grid.className = "memory-diagnostic-results";
        for (const [tool, item] of Object.entries(memory.results || {})) {
          const resultCard = document.createElement("article"); resultCard.className = "memory-diagnostic-result";
          const name = document.createElement("strong"); name.textContent = tool === "asan" ? "AddressSanitizer + UBSan" : displayLabel(tool);
          const status = document.createElement("span");
          status.textContent = item.status === "no_issue_detected_on_this_input" ? "No issue detected on this input" :
            item.status === "diagnostic_finding" ? "Potential memory issue detected" :
              item.status === "unavailable" ? "Not available in this environment" : displayLabel(item.status || "not run");
          resultCard.append(name, status);
          (item.findings || []).slice(0, 3).forEach(finding => {
            const detail = document.createElement("p"); detail.textContent = finding.evidence || finding.message || "Diagnostic reported a possible issue."; resultCard.append(detail);
          });
          grid.append(resultCard);
        }
        card.append(heading, note, grid); container.append(card);
      }
    }
    renderDifferentialResults(
      agent3bExecutionOutput,
      result?.agent3b_execution?.differential_comparisons || [],
      "Agent 3B edge",
      Math.max(0, 5 - (currentDraft?.agent3aFailureExamples || 0))
    );
    renderAgent4(agent4Output, result?.complexity_analysis);
    renderAgent5(agent5Output, result?.mathematical_verification);
    renderAgent6(agent6Output, result?.code_quality);
    renderGrade(gradingOutput, result);
  }

  const executeTestsButton = $("#agent3-execute");
  const executionOutput = $("#execution-output");
  const downloadReportButton = $("#download-report");
  const downloadTestCasesButton = $("#download-test-cases");
  const agent3aCard = $("#agent3a-card");
  const agent3bCard = $("#agent3b-card");
  const executionControls = $(".execution-controls");
  const agent4Card = $("#agent4-card");
  const agent5Card = $("#agent5-card");
  const agent6Card = $("#agent6-card");
  const gradingCard = $("#grading-card");

  function resetWorkflowProgress() {
    if (agent1Panel) agent1Panel.hidden = true;
    if (agent2Panel) agent2Panel.hidden = true;
    if (agent3Panel) agent3Panel.hidden = true;
    if (agent3aCard) agent3aCard.hidden = false;
    if (agent3bCard) agent3bCard.hidden = false;
    if (executionControls) executionControls.hidden = false;
    if (agent4Card) agent4Card.hidden = true;
    if (agent5Card) agent5Card.hidden = true;
    if (agent6Card) agent6Card.hidden = true;
    if (gradingCard) gradingCard.hidden = true;
    if (downloadTestCasesButton) downloadTestCasesButton.hidden = true;
    if (downloadReportButton) {
      downloadReportButton.hidden = true;
      downloadReportButton.disabled = true;
    }
    if (agent3Button) {
      agent3Button.hidden = false;
      agent3Button.disabled = false;
      agent3Button.textContent = "[ generate random + adversarial tests ]";
    }
    if (executeTestsButton) {
      executeTestsButton.hidden = false;
      executeTestsButton.disabled = false;
      executeTestsButton.textContent = "[ execute generated tests locally ]";
    }
    [
      agent1Summary, assignmentDraft, questionsPanel, referenceOutput,
      agent3Output, agent3bOutput, agent3aExecutionOutput,
      agent3bExecutionOutput, agent4Output, agent5Output, agent6Output,
      gradingOutput, executionOutput
    ].forEach(container => container?.replaceChildren());
    if (agent3SchemaSummary) agent3SchemaSummary.textContent = "";
    if (resultsSummary) resultsSummary.textContent = "";
    if (resultsFindings) resultsFindings.replaceChildren();
  }

  downloadTestCasesButton?.addEventListener("click", () => {
    if (!currentDraft?.testPlans) return;
    downloadGeneratedTests(
      currentDraft.testPlans,
      currentDraft.executionResult || null
    );
  });

  executeTestsButton?.addEventListener("click", async () => {
    if (!currentDraft?.submission_id || !instructorAuthenticated) {
      showToast("Instructor login and a prepared submission are required.");
      return;
    }

    if (!window.confirm(
      "Execute the generated C test inputs in the local development sandbox? Public execution remains disabled."
    )) return;

    if (agent2Panel) agent2Panel.hidden = true;
    executeTestsButton.disabled = true;
    executeTestsButton.textContent = "[ executing… ]";
    if (executionOutput) executionOutput.textContent = "Running local evaluation…";

    try {
      const result = await apiRequest("/api/ui/execute-tests", {
        submission_id: currentDraft.submission_id
      });
      currentDraft.executionResult = result;
      renderExecutionSummary(executionOutput, result);
      agent3aCard.hidden = true;
      agent3bCard.hidden = true;
      executionControls.hidden = true;
      agent4Card.hidden = false;
      agent5Card.hidden = false;
      agent6Card.hidden = false;
      gradingCard.hidden = false;
      downloadTestCasesButton.hidden = false;
      downloadReportButton.hidden = false;
      downloadReportButton.disabled = false;
      executeTestsButton.hidden = true;
      showToast("Execution evidence received. Review the final analysis and download the report.");
    } catch (error) {
      if (executionOutput) executionOutput.textContent = `Execution failed: ${error.message}`;
      showToast(`Execution failed: ${error.message}`);
    } finally {
      executeTestsButton.disabled = false;
      executeTestsButton.textContent = "[ execute generated tests locally ]";
    }
  });

  downloadReportButton?.addEventListener("click", async () => {
    if (!currentDraft?.submission_id || !instructorAuthenticated) {
      showToast("Instructor login and a prepared submission are required.");
      return;
    }

    downloadReportButton.disabled = true;
    downloadReportButton.textContent = "[ generating PDF… ]";
    try {
      const response = await fetch("/api/ui/generate-report", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/pdf"
        },
        body: JSON.stringify({ submission_id: currentDraft.submission_id })
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || `Report failed (HTTP ${response.status}).`);
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "autograder-evaluation-report.pdf";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      showToast("PDF report downloaded.");
    } catch (error) {
      showToast(`PDF download failed: ${error.message}`);
    } finally {
      downloadReportButton.disabled = false;
      downloadReportButton.textContent = "[ download full PDF report ]";
    }
  });

  logoutButton?.addEventListener("click", async () => {
    try {
      await apiRequest("/api/ui/logout");
    } catch (error) {
      showToast(`Logout request failed: ${error.message}`);
    }
    instructorAuthenticated = false;
    currentDraft = null;
    instructorControls.hidden = true;
    instructorLoginPanel.hidden = false;
    agent1Panel.hidden = true;
    agent2Panel.hidden = true;
    approveButton.disabled = true;
    showToast("Instructor session cookie cleared.");
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
      if (healthCheck) {
        healthCheck.classList.toggle("wired-positive", healthy);
        healthCheck.classList.toggle("wired-warning", !healthy);
      }
      if (healthDetail) healthDetail.textContent = healthy ? "API responded successfully" : "API returned an unhealthy status";
      if (healthState) healthState.textContent = healthy ? "ONLINE" : "CHECK";
      if (footerStatus) footerStatus.textContent = healthy ? "API connected" : "API issue";

      if (evaluateButton) {
        evaluateButton.disabled = false;
        evaluateButton.title = "Run static source analysis only; no code is executed.";
      }
    } catch (error) {
      if (serviceStatus) serviceStatus.textContent = "Service unavailable";
      if (healthCheck) healthCheck.textContent = "!";
      if (healthCheck) {
        healthCheck.classList.remove("wired-positive");
        healthCheck.classList.add("wired-warning");
      }
      if (healthDetail) healthDetail.textContent = "Could not reach /health";
      if (healthState) healthState.textContent = "OFFLINE";
      if (footerStatus) footerStatus.textContent = "API disconnected";
    }
  }

  checkHealth();

  // Magical cursor feedback: lightweight DOM particles, no external library.
  function createSpellBurst(x, y) {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const burst = document.createElement("span");
    burst.className = "spell-burst";
    burst.style.left = `${x}px`;
    burst.style.top = `${y}px`;

    for (let i = 0; i < 8; i++) {
      const particle = document.createElement("i");
      const angle = (Math.PI * 2 * i) / 8;
      const distance = 22 + Math.random() * 27;
      particle.style.setProperty("--dx", `${Math.cos(angle) * distance}px`);
      particle.style.setProperty("--dy", `${Math.sin(angle) * distance}px`);
      burst.append(particle);
    }
    document.body.append(burst);
    burst.addEventListener("animationend", () => burst.remove(), { once: true });
  }

  document.addEventListener("click", (event) => {
    createSpellBurst(event.clientX, event.clientY);
  });

})();
