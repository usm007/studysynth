"""Unit and regression tests for the Indian Computer-Based Examination (CBT) mode.

Validates that templates/web/app.template.html and examples/quiz.html implement
the complete, authentic Indian CBT interface (TCS iON / NTA style):
- Header strip: Candidate info (Aspirant), Section, Time Left countdown timer,
  Question Paper button, Instructions button
- Authentic 5-status Question Palette with live counters:
  Answered (Green), Not Answered (Red), Not Visited (Grey),
  Marked for Review (Purple), Answered & Marked for Review (Purple + Green dot)
- Essential Indian CBT Action dock: Save & Next, Clear Response, Save & Mark for Review,
  Mark for Review & Next, Previous, Next
- Exam Summary confirmation modal & Scorecard
- Review mode unlocking solutions, source citations, and distractor analysis
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "templates" / "web" / "app.template.html"
QUIZ_HTML = ROOT / "examples" / "quiz.html"


class TestIndianCBTMode(unittest.TestCase):
    def setUp(self):
        self.tpl_text = TPL.read_text(encoding="utf-8")
        self.quiz_text = QUIZ_HTML.read_text(encoding="utf-8")

    def test_cbt_header_elements(self):
        for text in [self.tpl_text, self.quiz_text]:
            self.assertIn('id="timerrow"', text)
            self.assertIn('id="examModeChip"', text)
            self.assertIn('id="examSection"', text)
            self.assertIn('id="btnQPaper"', text)
            self.assertIn('id="btnInstructions"', text)
            self.assertIn('id="timer"', text)
            self.assertIn('id="candidateChip"', text)
            self.assertIn("Aspirant", text)
            self.assertIn("CQ-2026-CBT", text)
            self.assertIn('id="finishtest"', text)
            self.assertIn('id="btnExitTest"', text)

    def test_cbt_action_buttons(self):
        for text in [self.tpl_text, self.quiz_text]:
            self.assertIn('id="submitbtn"', text)
            self.assertIn('id="clearbtn"', text)
            self.assertIn('id="saveMarkBtn"', text)
            self.assertIn('id="markbtn"', text)
            self.assertIn('id="prevbtn"', text)
            self.assertIn('id="nextbtn"', text)
            self.assertIn("Clear Response", text)
            self.assertIn("Save &amp; Mark for Review", text)

    def test_cbt_question_palette_and_5_states(self):
        for text in [self.tpl_text, self.quiz_text]:
            self.assertIn('id="examPanel"', text)
            self.assertIn('id="examPalette"', text)
            self.assertIn('id="examSubmit"', text)
            # Official 5 Indian CBT legend counters
            self.assertIn('id="cntAnswered"', text)
            self.assertIn('id="cntNotAnswered"', text)
            self.assertIn('id="cntUnvisited"', text)
            self.assertIn('id="cntMarked"', text)
            self.assertIn('id="cntMarkedAnswered"', text)
            # 5 state classes in CSS
            self.assertIn(".exam-q.is-answered", text)
            self.assertIn(".exam-q.is-notanswered", text)
            self.assertIn(".exam-q.is-unvisited", text)
            self.assertIn(".exam-q.is-marked", text)
            self.assertIn(".exam-q.is-current", text)

    def test_cbt_javascript_functions(self):
        for text in [self.tpl_text, self.quiz_text]:
            self.assertIn("function testCounts()", text)
            self.assertIn("function renderExamPalette()", text)
            self.assertIn("function openExamSubmitDialog()", text)
            self.assertIn("function showScorecardDialog()", text)
            self.assertIn("function openQuestionPaperDialog()", text)
            self.assertIn("function openInstructionsDialog()", text)
            self.assertIn("function clearCurrentResponse()", text)
            self.assertIn("function saveAndMark()", text)
            self.assertIn("function markForReviewAndNext()", text)
            self.assertIn("function exitTestMode()", text)

    def test_cbt_dialog_content(self):
        for text in [self.tpl_text, self.quiz_text]:
            self.assertIn('id="examDialog"', text)
            self.assertIn('id="examDialogBody"', text)
            self.assertIn('id="examExitStudyBtn"', text)
            self.assertIn("Exam Summary", text)
            self.assertIn("Scorecard", text)
            self.assertIn("General Examination Instructions", text)


    def test_cbt_start_screen_and_duration_config(self):
        for text in [self.tpl_text, self.quiz_text]:
            self.assertIn('id="examStartScreen"', text)
            self.assertIn('id="startExamSubject"', text)
            self.assertIn('id="startQCount"', text)
            self.assertIn('id="startMarking"', text)
            self.assertIn('id="cbtQCountOptions"', text)
            self.assertIn('id="cbtTimePerQOptions"', text)
            self.assertIn('id="cbtSumTitle"', text)
            self.assertIn('id="cbtSumCalc"', text)
            self.assertIn('id="btnStartExam"', text)
            self.assertIn('id="btnBackStudy"', text)
            self.assertIn('id="cbtDeclareCheck"', text)
            self.assertIn("function initTestStartScreen()", text)
            self.assertIn("function startCbtExam(", text)

    def test_navigation_buttons_and_auto_submit(self):
        with open(ROOT / "templates" / "web" / "app.template.html", encoding="utf-8") as f:
            text = f.read()
            self.assertIn("autoSubmitCurrentIfChosen", text)
            self.assertIn(".mode-item[data-mode=\"revision\"],.bnav-item[data-bnav=\"revision\"]", text)
            self.assertIn("function goNext(){ autoSubmitCurrentIfChosen();", text)
            self.assertIn("function goPrev(){ autoSubmitCurrentIfChosen();", text)



if __name__ == "__main__":
    unittest.main()
