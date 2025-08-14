import os
from flask import Flask, render_template, request
from dotenv import load_dotenv

# ------------------------------------------------------------
#  Configuration
# ------------------------------------------------------------
load_dotenv()
app = Flask(__name__)

# ------------------------------------------------------------
#  Constants
# ------------------------------------------------------------
TSAR_OPTION     = "Tsar! [You contradicted yourself!]"
ADMIT_OPT       = "I admit that I contradicted myself"
DENY_OPT        = "I do not admit that I contradicted myself"
ASK_OPTION      = "Ask a question"
COMPARE_OPTION  = "Compare phenomena"

WHY_OPT         = "Why?"
ACCEPT_OPT      = "I accept"
IMPROPER_OPT    = "I don't know this right now / That is an improper consequence"
IMPROPER_Q      = "Do you accept that this is an unknowable or improper consequence?"
YES_OPT         = "Yes"
NO_OPT          = "No"

# ------------------------------------------------------------
#  Helper builders
# ------------------------------------------------------------
def build_defender_explanations(subject, predicate, reason, copula):
    """
    Defender options depend on how complete the consequence is.
    - If subject+predicate present but reason missing: only Why? and I accept.
    - If full consequence (subject, predicate, reason): show standard options + "improper".
    """
    if subject and predicate and not reason:
        return [
            (WHY_OPT, ""),
            (ACCEPT_OPT, ""),
        ]
    if subject and predicate and reason:
        return [
            ("I accept", ""),
            ("The reason is not established", f"({subject} {copula} not {reason})"),
            ("There is no pervasion",
             f"(Whoever or whatever {copula} {reason} is not necessarily {predicate})"),
            (IMPROPER_OPT, ""),
        ]
    return []


def build_challenger_options(choice, subject, predicate, reason, copula):
    """
    Challenger options appear only after Defender has replied (choice != "").
    Includes classic follow-ups + Tsar + Ask a question + Compare phenomena.
    Suppressed when the defender chose IMPROPER_OPT (handled via Yes/No prompt).
    """
    if choice == IMPROPER_OPT:
        return []

    base = []
    if choice == "The reason is not established":
        base = [
            f"{subject} {copula} {reason}, because of being…",
            f"{subject} {copula} not {reason}, because of being…",
            "Write a new consequence",
        ]
    elif choice == "There is no pervasion":
        base = [
            f"Whoever or whatever {copula} {reason} is necessarily {predicate}, because of being…",
            f"Whoever or whatever {copula} {reason} is not necessarily {predicate}, because of being…",
            "Write a new consequence",
        ]
    if choice:
        base.append(ASK_OPTION)
        base.append(COMPARE_OPTION)
        base.append(TSAR_OPTION)
    return base


def make_transcript(steps, flipped_flag):
    """Return a readable transcript of the entire debate."""
    p1, p2 = ("Player 1", "Player 2") if flipped_flag == "0" else ("Player 2", "Player 1")
    lines = []
    for idx, st in enumerate(steps, 1):
        if st["subject"] and st["predicate"] and st["reason"]:
            lines.append(f"{idx}. It follows that {st['subject']} {st['copula']} "
                         f"{st['predicate']}, because of being {st['reason']}.")
        if st["defender_choice"]:
            lines.append(f"   {p2} (Defender): {st['defender_choice']}")

        if st.get("improper_ack"):
            lines.append(f"   {p1} (Challenger) — {IMPROPER_Q} {st['improper_ack']}")

        if st["challenger_choice"] == ASK_OPTION:
            if st["question_text"]:
                lines.append(f"   {p1} (Challenger) — Question: {st['question_text']}")
            if st["answer_text"]:
                lines.append(f"   {p2} (Defender) — Answer: {st['answer_text']}")

        elif st["challenger_choice"] == COMPARE_OPTION:
            if st["compare_a"] or st["compare_b"]:
                lines.append(f"   {p1} (Challenger) — Compare: "
                             f"What is the relationship between {st['compare_a']} and {st['compare_b']}?")
            if st["compare_option"]:
                lines.append(f"   {p2} (Defender) — Diagram choice: {st['compare_option']}")

        elif st["challenger_choice"]:
            msg = st["challenger_choice"]
            if st["challenger_reason"]:
                msg += f" — because of being {st['challenger_reason']}"
            lines.append(f"   {p1} (Challenger): {msg}")

        if st["contradiction_choice"]:
            lines.append(f"   {p2} (Defender): {st['contradiction_choice']}")
    return lines


# ------------------------------------------------------------
#  Flask route
# ------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    steps, transcript = [], ""
    flipped = "0"          # 0 = default roles, 1 = switched

    if request.method == "POST":
        flipped = request.form.get("flipped", "0")
        if "switch_roles" in request.form:
            flipped = "1" if flipped == "0" else "0"

        step_count = int(request.form.get("step_count", 1))

        # ---------- Re-hydrate all previous rows ----------
        for i in range(step_count):
            g   = lambda field, default="": request.form.get(f"{field}_{i}", default).strip()

            subject, copula = g("subject"), g("copula", "is")
            predicate, reason = g("predicate"), g("reason")

            defender_choice     = g("defender_choice")
            challenger_choice   = g("challenger_choice")
            challenger_reason   = g("challenger_reason")

            contradiction_choice = g("contradiction_choice")

            # Ask-a-question fields
            question_text = g("question_text")
            answer_text   = g("answer_text")

            # Compare phenomena fields
            compare_a         = g("compare_a")
            compare_b         = g("compare_b")
            compare_option    = g("compare_option")
            compare_locked    = g("compare_locked")  # "1" when finalized

            # Improper/unknowable follow-up
            improper_ack      = g("improper_ack")

            steps.append({
                "subject": subject, "copula": copula,
                "predicate": predicate, "reason": reason,
                "consequence": (
                    f"It follows that {subject} {copula} {predicate}, because of being {reason}."
                    if subject and predicate and reason else ""
                ),

                "defender_choice": defender_choice,
                "defender_explanations": [],  # fill after special flows handled

                "challenger_options": [],     # fill after special flows handled
                "challenger_choice": challenger_choice,
                "challenger_reason": challenger_reason,

                "contradiction_options": (
                    [ADMIT_OPT, DENY_OPT]
                    if challenger_choice == TSAR_OPTION and not contradiction_choice else []
                ),
                "contradiction_choice": contradiction_choice,

                # Ask-a-question
                "question_text": question_text,
                "answer_text": answer_text,

                # Compare phenomena
                "compare_a": compare_a,
                "compare_b": compare_b,
                "compare_option": compare_option,
                "compare_locked": compare_locked,  # "1" if finalized

                # Improper/unknowable path
                "improper_ack": improper_ack,

                # UI helpers
                "need_reason": "0",           # turned on when Defender presses WHY on a reasonless claim
                "need_improper_ack": "0",     # turned on when Defender presses IMPROPER
            })

        # ---------------- Special handling: WHY? completes the reasoning on the SAME step ----------------
        if steps:
            last = steps[-1]
            # Case: initial assertion with no reason
            if last["subject"] and last["predicate"] and not last["reason"]:
                if last["defender_choice"] == WHY_OPT:
                    if last["challenger_reason"]:
                        # Challenger supplied the missing reason; finalize this same step
                        last["reason"] = last["challenger_reason"]
                        last["challenger_reason"] = ""
                        # Reset defender choice so they can now pick from the full menu for the completed consequence
                        last["defender_choice"] = ""
                        # Refresh consequence text
                        last["consequence"] = (
                            f"It follows that {last['subject']} {last['copula']} {last['predicate']}, "
                            f"because of being {last['reason']}."
                        )
                    else:
                        # Prompt challenger to complete the reasoning
                        last["need_reason"] = "1"

        # ---------- After special WHY consolidation, compute menus for each step ----------
        for st in steps:
            st["defender_explanations"] = build_defender_explanations(
                st["subject"], st["predicate"], st["reason"], st["copula"]
            )
            if st["defender_choice"]:
                st["challenger_options"] = build_challenger_options(
                    st["defender_choice"], st["subject"], st["predicate"], st["reason"], st["copula"]
                )
            else:
                st["challenger_options"] = st.get("challenger_options", [])

            # Flag if improper path needs Yes/No
            if st["defender_choice"] == IMPROPER_OPT and not st.get("improper_ack"):
                st["need_improper_ack"] = "1"

        # ---------- Quick bottom buttons: set challenger choice on the current step ----------
        quick = request.form.get("quick_choice", "").strip()
        if quick in (ASK_OPTION, COMPARE_OPTION) and steps:
            last = steps[-1]
            # Only allow if we're not in the middle of a WHY or improper follow-up
            if not last["challenger_choice"] and last["need_reason"] != "1" and last["need_improper_ack"] != "1":
                last["challenger_choice"] = quick

        # ---------- Determine if a new step is needed ----------
        last = steps[-1]

        accept_turn  = last["defender_choice"] == "I accept"
        new_conseq   = last["challenger_choice"] == "Write a new consequence"
        follow_up    = bool(last["challenger_reason"]) and last["challenger_choice"] not in (ASK_OPTION, COMPARE_OPTION)
        contra_done  = bool(last["contradiction_choice"])

        ask_answer_done = (last["challenger_choice"] == ASK_OPTION and bool(last["answer_text"]))

        compare_done = (
            last["challenger_choice"] == COMPARE_OPTION
            and bool(last["compare_a"]) and bool(last["compare_b"])
            and bool(last["compare_option"])
        )

        improper_done = (last["defender_choice"] == IMPROPER_OPT and last.get("improper_ack") in (YES_OPT, NO_OPT))

        # If we still need a reason (WHY) or need improper ack, do NOT advance yet
        block_advance = (last["need_reason"] == "1") or (last["need_improper_ack"] == "1")

        if not block_advance and (accept_turn or new_conseq or follow_up or contra_done or ask_answer_done or compare_done or improper_done):
            # Default: carry Challenger's typed reasoning into the next consequence
            new_subject   = last["subject"]
            new_predicate = last["predicate"]
            new_copula    = last["copula"]
            new_reason    = last["challenger_reason"]

            # Fully blank for these situations (do NOT carry the reason)
            if accept_turn or new_conseq or contra_done or ask_answer_done or compare_done or improper_done:
                new_subject = new_predicate = ""
                new_copula  = "is"
                new_reason  = ""

            # Defender-logic flips (only if we didn't blank)
            if not (accept_turn or new_conseq or contra_done or ask_answer_done or compare_done or improper_done):
                # Build the exact positive/negative option strings to detect negation choice
                rne_pos = f"{last['subject']} {last['copula']} {last['reason']}, because of being…"
                rne_neg = f"{last['subject']} {last['copula']} not {last['reason']}, because of being…"

                nop_pos = f"Whoever or whatever {last['copula']} {last['reason']} is necessarily {last['predicate']}, because of being…"
                nop_neg = f"Whoever or whatever {last['copula']} {last['reason']} is not necessarily {last['predicate']}, because of being…"

                if last["defender_choice"] == "The reason is not established":
                    # Predicate becomes (not) reason depending on negation choice
                    new_predicate = f"not {last['reason']}" if last["challenger_choice"] == rne_neg else last["reason"]

                elif last["defender_choice"] == "There is no pervasion":
                    new_subject = f"Whoever or whatever {new_copula} {last['reason']}"
                    # Predicate becomes (not) necessarily predicate depending on negation choice
                    new_predicate = (
                        f"not necessarily {last['predicate']}"
                        if last["challenger_choice"] == nop_neg
                        else f"necessarily {last['predicate']}"
                    )

            # If we finalized a comparison, lock that step so its dropdown becomes read-only
            if compare_done:
                steps[-1]["compare_locked"] = "1"

            steps.append({
                "subject": new_subject, "copula": new_copula,
                "predicate": new_predicate, "reason": new_reason,
                "consequence": (
                    f"It follows that {new_subject} {new_copula} {new_predicate}, "
                    f"because of being {new_reason}."
                    if new_subject and new_predicate and new_reason else ""
                ),

                "defender_choice": "",
                "defender_explanations": (
                    build_defender_explanations(new_subject, new_predicate, new_reason, new_copula)
                    if new_subject and new_predicate and new_reason else []
                ),

                "challenger_options": [],
                "challenger_choice": "",
                "challenger_reason": "",

                "contradiction_options": [],
                "contradiction_choice": "",

                "question_text": "",
                "answer_text": "",

                "compare_a": "",
                "compare_b": "",
                "compare_option": "",
                "compare_locked": "",

                "improper_ack": "",
                "need_reason": "0",
                "need_improper_ack": "0",
            })

        # ---------- Transcript button ----------
        if "generate_transcript" in request.form:
            transcript = "\n".join(make_transcript(steps, flipped))

    # ---------- First page load ----------
    if not steps:
        steps.append({
            "subject": "", "copula": "is", "predicate": "", "reason": "",
            "consequence": "",
            "defender_choice": "", "defender_explanations": [],
            "challenger_options": [], "challenger_choice": "", "challenger_reason": "",
            "contradiction_options": [], "contradiction_choice": "",
            "question_text": "", "answer_text": "",
            "compare_a": "", "compare_b": "", "compare_option": "", "compare_locked": "",
            "improper_ack": "",
            "need_reason": "0",
            "need_improper_ack": "0",
        })

    return render_template(
        "index.html",
        steps=steps,
        step_count=len(steps),
        flipped=flipped,
        transcript=transcript,
        ASK_OPTION=ASK_OPTION,
        COMPARE_OPTION=COMPARE_OPTION,
        WHY_OPT=WHY_OPT,
        ACCEPT_OPT=ACCEPT_OPT,
        IMPROPER_Q=IMPROPER_Q,
        YES_OPT=YES_OPT,
        NO_OPT=NO_OPT,
    )


if __name__ == "__main__":
    app.run(debug=True)
