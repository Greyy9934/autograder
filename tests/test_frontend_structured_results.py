from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/static/app.js").read_text()
HTML = (ROOT / "app/templates/index.html").read_text()
CSS = (ROOT / "app/static/styles.css").read_text()


def test_agent_results_use_structured_containers():
    assert 'id="assignment-draft" class="structured-results"' in HTML
    assert 'id="reference-output" class="structured-results"' in HTML
    assert "<pre id=\"assignment-draft\"" not in HTML
    assert "<pre id=\"reference-output\"" not in HTML


def test_every_analysis_stage_has_its_own_card_and_output_container():
    for stage in ("agent1-result", "agent2-result", "agent3a-card", "agent3b-card",
                  "agent4-card", "agent5-card", "agent6-card", "grading-card"):
        assert f'id="{stage}"' in HTML
    for output in ("agent3a-execution-output", "agent3b-output",
                   "agent3b-execution-output", "agent4-output", "agent5-output",
                   "agent6-output", "grading-output"):
        assert f'id="{output}"' in HTML
    assert ".agent-stage-card" in CSS


def test_generated_cases_are_hidden_except_for_capped_failure_examples():
    assert "issues.slice(0, shown)" in JS
    assert "maxExamples = 5" in JS
    assert "Download test cases (.txt)" in JS
    assert "JSON.stringify(value, null, 2)" not in JS


def test_raw_json_result_renderer_is_removed():
    assert "function showJson(" not in JS
    assert "showJson(" not in JS
    assert "renderAssignmentSummary(assignmentDraft, data)" in JS
    assert "renderReferenceSolutions(referenceOutput, references)" in JS
    assert "View reference implementation" in JS


def test_user_results_hide_machine_metadata_and_defer_optional_details():
    grade_renderer = JS.split("function renderGrade(", 1)[1].split("function renderExecutionSummary(", 1)[0]
    assert "grade_snapshot_backend" not in grade_renderer
    assert "test_suite_fingerprint" not in grade_renderer
    assert "Timeouts and infrastructure errors are inconclusive" in grade_renderer
    assert 'conditionsTitle.textContent = "Proof conditions and assumptions"' in JS
    assert 'summary.textContent = "Analysis notes"' in JS
    assert "slice(0, 5)" in JS
    workflow = JS.split("agent3Button?.addEventListener", 1)[1].split("function buildGeneratedTestsText", 1)[0]
    assert "generator_program" not in workflow
    assert 'addText(agent3Output, "h3", "Approved input format")' not in workflow
    assert "grade_snapshot_backend" not in JS
    assert "assignment_spec_fingerprint}" not in JS


def test_user_facing_result_card_styles_match_board_theme():
    assert ".reference-solution-card" in CSS
    assert "#ffffee" in CSS
    assert "#880000" in CSS


def test_preflight_and_memory_diagnostics_are_visible_in_the_workflow():
    assert "Preflight before problem analysis" in JS
    assert "compiler_stderr" in JS
    assert '/api/ui/preflight' in JS
    assert 'preflightData.compilation?.status !== "compiled"' in JS
    assert "GCC compiled the program before Agent 1 ran" in JS
    assert "AddressSanitizer + UBSan" in JS
    assert "Valgrind" in JS


def test_system_status_colors_follow_live_health_text():
    assert "unhealthy|unreachable|check)\\b|could not reach" in HTML
    assert "#system-status .wired-positive" in CSS
    assert "#system-status .wired-warning" in CSS
    assert 'healthCheck.classList.toggle("wired-positive", healthy)' in JS
    assert 'healthCheck.classList.add("wired-warning")' in JS

def test_frieren_loader_uses_a_present_walking_asset_on_all_pages():
    import xml.etree.ElementTree as ET

    asset = ROOT / "app/static/frieren-loading.svg"
    ET.parse(asset)
    for page in ("index", "workflow", "rubric", "principles"):
        html = (ROOT / f"app/templates/{page}.html").read_text()
        assert "/static/frieren-loading.svg" in html
        assert "/static/frieren-loading.png" not in html
    assert "@keyframes frieren-walk-across" in CSS
    assert "prefers-reduced-motion: reduce" in CSS
    svg = asset.read_text()
    assert "@keyframes leg-a" in svg
    assert "@keyframes leg-b" in svg

def test_ai_content_is_rendered_as_text_not_html():
    assert "function renderStructured(" in JS
    assert "document.createElement(" in JS
    assert "textContent =" in JS
    assert "innerHTML" not in JS


def test_structured_result_styles_exist():
    for selector in (
        ".structured-results",
        ".result-section",
        ".result-field",
        ".result-list",
        ".result-code",
    ):
        assert selector in CSS


def test_agent_result_containers_are_accessible():
    assert 'id="assignment-draft" class="structured-results" aria-live="polite"' in HTML
    assert 'id="reference-output" class="structured-results" aria-live="polite"' in HTML


def test_workflow_progressively_hides_completed_agent_stages():
    assert 'id="agent4-card" hidden' in HTML
    assert 'id="agent5-card" hidden' in HTML
    assert 'id="agent6-card" hidden' in HTML
    assert 'id="grading-card" hidden' in HTML
    assert "agent1Panel.hidden = true" in JS
    assert "agent2Panel.hidden = true" in JS
    assert "agent3aCard.hidden = true" in JS
    assert "agent3bCard.hidden = true" in JS
    assert "resetWorkflowProgress();" in JS
    assert 'id="download-test-cases"' in HTML


def test_agent1_provider_and_schema_failures_do_not_blame_user_for_schema():
    assert "Agent 1 could not complete the reconstruction" in JS
    assert "The schema is generated by Agent 1; it is not a user input." in JS
    assert "schema entry is not required from you" in JS
    assert "clarify the input grammar and bounds before continuing" not in JS
