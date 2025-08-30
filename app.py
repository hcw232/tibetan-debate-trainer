import os
from flask import Flask, render_template, request
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------
TSAR_OPTION       = "Tsar! [You contradicted yourself!]"
ADMIT_OPT         = "I admit that I contradicted myself"
DENY_OPT          = "I do not admit that I contradicted myself"
ASK_OPTION        = "Ask a question"
COMPARE_OPTION    = "Compare phenomena"
NEW_CONSEQ_OPT    = "Write a new consequence"
WHY_OPTION        = "Why?"

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def build_defender_explanations(subject, predicate, reason, copula):
    if subject and predicate and not reason:
        return [("I accept", ""), (WHY_OPTION, "")]
    if subject and predicate and reason:
        return [
            ("I accept", ""),
            ("The reason is not established", f"({subject} {copula} not {reason})"),
            ("There is no pervasion",
             f"(Whoever or whatever {copula} {reason} is not necessarily {predicate})"),
            ("I don't know this right now / That is an improper consequence", ""),
        ]
    return []


def build_challenger_options(choice, subject, predicate, reason, copula):
    base = []
    if choice == "The reason is not established":
        base = [
            f"{subject} {copula} {reason}, because of being…",
            f"{subject} {copula} not {reason}, because of being…",
        ]
    elif choice == "There is no pervasion":
        base = [
            f"Whoever or whatever {copula} {reason} is necessarily {predicate}, because of being…",
            f"Whoever or whatever {copula} {reason} is not necessarily {predicate}, because of being…",
        ]
    if choice:
        base.extend([ASK_OPTION, COMPARE_OPTION, NEW_CONSEQ_OPT, TSAR_OPTION])
    return base


def general_challenger_options():
    return [ASK_OPTION, COMPARE_OPTION, NEW_CONSEQ_OPT, TSAR_OPTION]


def make_transcript(steps, preface=""):
    lines = []
    if preface.strip():
        lines.append("Preface / Discussion Summary:")
        lines.append(preface.strip())
        lines.append("")

    for idx, st in enumerate(steps, 1):
        # Role-switch marker line
        if st.get("role_switch") == "1":
            lines.append(f"— Roles switched: From here on, {st['switch_to_cha']} and {st['switch_to_def']}.")
            continue

        cha = st.get("cha_label", "Player 1 (Challenger)")
        deff = st.get("def_label", "Player 2 (Defender)")

        # Consequence
        if st["subject"] and st["predicate"] and st["reason"]:
            lines.append(f"{idx}. It follows that {st['subject']} {st['copula']} "
                         f"{st['predicate']}, because of being {st['reason']}.")
        elif st["subject"] and st["predicate"] and not st["reason"]:
            lines.append(f"{idx}. It follows that {st['subject']} {st['copula']} {st['predicate']} (reason pending).")

        # Defender response
        if st["defender_choice"]:
            lines.append(f"   {deff}: {st['defender_choice']}")

        # Why? pending
        if st["need_reason"] == "1" and not st["reason"]:
            lines.append(f"   {cha}: (awaiting completion of the reason)")

        # Ask — persist regardless of later moves
        if st.get("question_text") or st.get("answer_text"):
            if st.get("question_text"):
                lines.append(f"   {cha} — Question: {st['question_text']}")
            if st.get("answer_text"):
                lines.append(f"   {deff} — Answer: {st['answer_text']}")

        # Generic challenger follow-ups (not Tsar/Ask)
        if st["challenger_choice"] and st["challenger_choice"] not in [TSAR_OPTION, ASK_OPTION]:
            msg = st["challenger_choice"]
            if st["challenger_reason"]:
                msg += f" — because of being {st['challenger_reason']}"
            lines.append(f"   {cha}: {msg}")

        # Compare — persist regardless of later moves
        if st["compare_a"] or st["compare_b"]:
            lines.append(f"   {cha} — Compare: "
                         f"What is the relationship between {st['compare_a']} and {st['compare_b']}?")
        if st["compare_option"]:
            lines.append(f"   {deff} — Diagram choice: {st['compare_option']}")

        # Tsar — persist regardless of later moves
        if st.get("tsar_called") == "1" or st["challenger_choice"] == TSAR_OPTION or st["contradiction_choice"]:
            lines.append(f"   {cha}: Tsar! You contradicted yourself.")
            if st["contradiction_choice"]:
                lines.append(f"   {deff}: {st['contradiction_choice']}")

    return lines


def determine_turn_state(st):
    if st.get("role_switch") == "1":
        return {"who": "challenger", "mode": "role_flip_marker", "label": "Roles switched"}

    if st.get("need_reason") == "1" and not st["reason"]:
        return {"who": "challenger", "mode": "need_reason", "label": "Complete the reasoning"}

    if st["challenger_choice"] == ASK_OPTION:
        if not st["question_text"]:
            return {"who": "challenger", "mode": "ask_question", "label": "Ask a question"}
        if st["question_text"] and not st["answer_text"]:
            return {"who": "defender", "mode": "answer_question", "label": "Answer the question"}
        return {"who": "challenger", "mode": "challenger_menu", "label": "Choose next move"}

    if st["challenger_choice"] == COMPARE_OPTION:
        if not (st["compare_a"] and st["compare_b"]):
            return {"who": "challenger", "mode": "compare_names", "label": "Enter items to compare"}
        if not st["compare_option"]:
            return {"who": "defender", "mode": "compare_choice", "label": "Choose a diagram"}
        return {"who": "challenger", "mode": "challenger_menu", "label": "Choose next move"}

    if st["challenger_choice"] == TSAR_OPTION:
        if not st["contradiction_choice"]:
            return {"who": "defender", "mode": "tsar_decide", "label": "Admit or deny the Tsar"}
        return {"who": "challenger", "mode": "challenger_menu", "label": "Choose next move"}

    if not st["subject"] and not st["predicate"] and not st["reason"]:
        return {"who": "challenger", "mode": "new_consequence", "label": "Propose a consequence"}

    if st["subject"] and st["predicate"] and not st["defender_choice"]:
        return {"who": "defender", "mode": "defender_choice", "label": "Respond to the consequence"}

    if st["defender_choice"]:
        if st["challenger_choice"] and (st["challenger_choice"] not in [ASK_OPTION, COMPARE_OPTION, TSAR_OPTION, NEW_CONSEQ_OPT]) and not st["challenger_reason"]:
            return {"who": "challenger", "mode": "challenger_menu", "label": "Complete the reasoning"}
        return {"who": "challenger", "mode": "challenger_menu", "label": "Choose next move"}

    return {"who": "challenger", "mode": "new_consequence", "label": "Propose a consequence"}


def pick_active_index(steps):
    priority = [
        "need_reason",
        "ask_question",
        "answer_question",
        "compare_names",
        "compare_choice",
        "tsar_decide",
        "defender_choice",
        "new_consequence",
        "challenger_menu",
    ]
    for mode in priority:
        for i in range(len(steps) - 1, -1, -1):
            if determine_turn_state(steps[i])["mode"] == mode:
                return i
    for i in range(len(steps) - 1, -1, -1):
        if determine_turn_state(steps[i])["mode"] != "role_flip_marker":
            return i
    return max(0, len(steps) - 1)


def compute_role_labels(steps, initial_flipped_flag):
    base_flip = 1 if (initial_flipped_flag == "1") else 0
    parity = base_flip
    for st in steps:
        if parity == 0:
            cha = "Player 1 (Challenger)"
            deff = "Player 2 (Defender)"
        else:
            cha = "Player 2 (Challenger)"
            deff = "Player 1 (Defender)"
        st["cha_label"] = cha
        st["def_label"] = deff
        st["effective_flipped"] = "1" if parity == 1 else "0"

        if st.get("role_switch") == "1":
            next_parity = parity ^ 1
            if next_parity == 0:
                to_cha = "Player 1 becomes Challenger"
                to_def = "Player 2 becomes Defender"
            else:
                to_cha = "Player 2 becomes Challenger"
                to_def = "Player 1 becomes Defender"
            st["switch_to_cha"] = to_cha
            st["switch_to_def"] = to_def

        if st.get("role_switch") == "1":
            parity ^= 1

    if parity == 0:
        return "Player 1 (Challenger)", "Player 2 (Defender)"
    else:
        return "Player 2 (Challenger)", "Player 1 (Defender)"


# ------------------------------------------------------------
# Route
# ------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    steps, transcript = [], ""
    flipped_initial = "0"
    preface_text = ""

    if request.method == "POST":
        flipped_initial = request.form.get("flipped", "0")
        preface_text = request.form.get("preface_text", "").strip()

        step_count = int(request.form.get("step_count", 1))
        did_submit_continue = "submit_continue" in request.form
        wants_transcript = "generate_transcript" in request.form
        wants_return = "close_transcript" in request.form
        did_switch_roles = "switch_roles" in request.form

        # Rehydrate
        for i in range(step_count):
            g = lambda field, default="": request.form.get(f"{field}_{i}", default).strip()

            subject, copula = g("subject"), g("copula", "is")
            predicate, reason = g("predicate"), g("reason")

            defender_choice     = g("defender_choice")
            challenger_choice   = g("challenger_choice")
            challenger_reason   = g("challenger_reason")

            contradiction_choice = g("contradiction_choice")

            # Ask
            question_text = g("question_text")
            answer_text   = g("answer_text")

            # Compare
            compare_a      = g("compare_a")
            compare_b      = g("compare_b")
            compare_option = g("compare_option")
            compare_locked = g("compare_locked")

            # Tsar persistence flag
            tsar_called = g("tsar_called", "0")
            if challenger_choice == TSAR_OPTION or contradiction_choice:
                tsar_called = "1"

            # "Why?"
            need_reason = g("need_reason", "0")
            if defender_choice == WHY_OPTION and not reason:
                need_reason = "1"

            # Role switch marker
            role_switch = g("role_switch", "0")

            defender_expl = build_defender_explanations(subject, predicate, reason, copula)

            # Base challenger options
            challenger_opts = []
            if defender_choice and need_reason != "1":
                challenger_opts = build_challenger_options(defender_choice, subject, predicate, reason, copula)

            # Special flows surface general menu when resolved
            if need_reason != "1":
                if (challenger_choice == ASK_OPTION and question_text and answer_text) or \
                   (challenger_choice == COMPARE_OPTION and compare_a and compare_b and compare_option) or \
                   (challenger_choice == TSAR_OPTION and contradiction_choice) or \
                   (defender_choice == "I accept"):
                    challenger_opts = general_challenger_options()

            steps.append({
                "subject": subject, "copula": copula,
                "predicate": predicate, "reason": reason,
                "consequence": (
                    f"It follows that {subject} {copula} {predicate}, because of being {reason}."
                    if subject and predicate and reason else ""
                ),

                "defender_choice": defender_choice,
                "defender_explanations": defender_expl,

                "challenger_options": challenger_opts,
                "challenger_choice": challenger_choice,
                "challenger_reason": challenger_reason,

                # Tsar
                "contradiction_options": (
                    [ADMIT_OPT, DENY_OPT]
                    if challenger_choice == TSAR_OPTION and not contradiction_choice else []
                ),
                "contradiction_choice": contradiction_choice,
                "tsar_called": tsar_called,

                # Ask
                "question_text": question_text,
                "answer_text": answer_text,

                # Compare
                "compare_a": compare_a,
                "compare_b": compare_b,
                "compare_option": compare_option,
                "compare_locked": compare_locked,

                # Why?
                "need_reason": need_reason,

                # Role switch marker
                "role_switch": role_switch,
            })

        # 🔎 Determine which step was actually active on this submit
        active_idx = pick_active_index(steps)
        cur = steps[active_idx] if steps else None

        # --- Per-turn transitions (apply to the active step, not just the last) ---
        if cur:
            # Complete "Why?"
            if cur["need_reason"] == "1" and cur["challenger_reason"]:
                cur["reason"] = cur["challenger_reason"].strip()
                cur["need_reason"] = "0"
                cur["consequence"] = (
                    f"It follows that {cur['subject']} {cur['copula']} {cur['predicate']}, "
                    f"because of being {cur['reason']}."
                )
                cur["defender_choice"] = ""
                cur["defender_explanations"] = build_defender_explanations(
                    cur["subject"], cur["predicate"], cur["reason"], cur["copula"]
                )
                cur["challenger_choice"] = ""
                cur["challenger_options"] = []

            # Compare: lock when submitted (to persist choice/diagram)
            compare_done = (
                cur["challenger_choice"] == COMPARE_OPTION
                and bool(cur["compare_a"]) and bool(cur["compare_b"])
                and bool(cur["compare_option"])
            )
            if compare_done and did_submit_continue:
                cur["compare_locked"] = "1"
                if cur["need_reason"] != "1":
                    cur["challenger_options"] = general_challenger_options()

            # Ask answered -> general menu (keep Q/A)
            if cur["challenger_choice"] == ASK_OPTION and cur["answer_text"] and cur["need_reason"] != "1":
                cur["challenger_options"] = general_challenger_options()

            # Tsar decided -> general menu (preserve tsar_called)
            if cur["challenger_choice"] == TSAR_OPTION and cur["contradiction_choice"] and cur["need_reason"] != "1":
                cur["tsar_called"] = "1"
                cur["challenger_options"] = general_challenger_options()

            # Defender accepted -> challenger menu
            if cur["defender_choice"] == "I accept" and cur["need_reason"] != "1":
                cur["challenger_options"] = general_challenger_options()

            # Autogenerated follow-up consequence
            if (
                cur["defender_choice"] in ["The reason is not established", "There is no pervasion"]
                and cur["challenger_choice"]
                and cur["challenger_choice"] not in [ASK_OPTION, COMPARE_OPTION, TSAR_OPTION, NEW_CONSEQ_OPT]
                and cur["challenger_reason"].strip()
            ):
                choice_txt = cur["challenger_choice"].strip()
                new_subject = cur["subject"]
                new_copula  = cur["copula"]
                new_predicate = cur["predicate"]
                new_reason = cur["challenger_reason"].strip()

                if cur["defender_choice"] == "The reason is not established":
                    if choice_txt.startswith(f"{cur['subject']} {cur['copula']} not {cur['reason']}"):
                        new_predicate = f"not {cur['reason']}"
                    else:
                        new_predicate = cur["reason"]
                elif cur["defender_choice"] == "There is no pervasion":
                    new_subject = f"Whoever or whatever {cur['copula']} {cur['reason']}"
                    if "not necessarily" in choice_txt:
                        new_predicate = f"not necessarily {cur['predicate']}"
                    else:
                        new_predicate = f"necessarily {cur['predicate']}"

                steps.append({
                    "subject": new_subject, "copula": new_copula,
                    "predicate": new_predicate, "reason": new_reason,
                    "consequence": f"It follows that {new_subject} {new_copula} {new_predicate}, because of being {new_reason}.",

                    "defender_choice": "",
                    "defender_explanations": build_defender_explanations(new_subject, new_predicate, new_reason, new_copula),

                    "challenger_options": [],
                    "challenger_choice": "",
                    "challenger_reason": "",

                    "contradiction_options": [],
                    "contradiction_choice": "",
                    "tsar_called": "0",

                    "question_text": "",
                    "answer_text": "",

                    "compare_a": "",
                    "compare_b": "",
                    "compare_option": "",
                    "compare_locked": "",

                    "need_reason": "0",
                    "role_switch": "0",
                })

            # ✅ Handle "Write a new consequence" from the active step
            elif cur["challenger_choice"] == NEW_CONSEQ_OPT and cur["need_reason"] != "1":
                steps.append({
                    "subject": "", "copula": "is",
                    "predicate": "", "reason": "",
                    "consequence": "",

                    "defender_choice": "",
                    "defender_explanations": [],

                    "challenger_options": [],
                    "challenger_choice": "",
                    "challenger_reason": "",

                    "contradiction_options": [],
                    "contradiction_choice": "",
                    "tsar_called": "0",

                    "question_text": "",
                    "answer_text": "",

                    "compare_a": "",
                    "compare_b": "",
                    "compare_option": "",
                    "compare_locked": "",

                    "need_reason": "0",
                    "role_switch": "0",
                })

        # Normalize earlier Why? steps if reason filled later
        for s in steps:
            if s["defender_choice"] == WHY_OPTION and s["reason"]:
                s["need_reason"] = "0"
                s["defender_choice"] = ""
                s["defender_explanations"] = build_defender_explanations(
                    s["subject"], s["predicate"], s["reason"], s["copula"]
                )
                s["challenger_choice"] = ""
                s["challenger_options"] = []

        # Append a role-switch marker step if requested
        if did_switch_roles:
            steps.append({
                "subject": "", "copula": "is",
                "predicate": "", "reason": "",
                "consequence": "",
                "defender_choice": "",
                "defender_explanations": [],
                "challenger_options": [],
                "challenger_choice": "",
                "challenger_reason": "",
                "contradiction_options": [],
                "contradiction_choice": "",
                "tsar_called": "0",
                "question_text": "",
                "answer_text": "",
                "compare_a": "",
                "compare_b": "",
                "compare_option": "",
                "compare_locked": "",
                "need_reason": "0",
                "role_switch": "1",
            })

        # Build per-step role labels and get current labels for Turn Bar
        current_cha_lab, current_def_lab = compute_role_labels(steps, flipped_initial)

        # Transcript
        if wants_transcript and not wants_return:
            transcript = "\n".join(make_transcript(steps, preface=preface_text))

    # First load
    if not steps:
        steps.append({
            "subject": "", "copula": "is", "predicate": "", "reason": "",
            "consequence": "",
            "defender_choice": "", "defender_explanations": [],
            "challenger_options": [], "challenger_choice": "", "challenger_reason": "",
            "contradiction_options": [], "contradiction_choice": "",
            "tsar_called": "0",
            "question_text": "", "answer_text": "",
            "compare_a": "", "compare_b": "", "compare_option": "", "compare_locked": "",
            "need_reason": "0",
            "role_switch": "0",
        })
        compute_role_labels(steps, flipped_initial)
        current_cha_lab, current_def_lab = steps[0]["cha_label"], steps[0]["def_label"]

    current_idx = pick_active_index(steps)
    turn_state = determine_turn_state(steps[current_idx])

    return render_template(
        "index.html",
        steps=steps,
        step_count=len(steps),
        flipped_initial=flipped_initial,
        transcript=transcript,
        preface_text=preface_text,
        ASK_OPTION=ASK_OPTION,
        COMPARE_OPTION=COMPARE_OPTION,
        current_idx=current_idx,
        turn_state=turn_state,
        current_cha_lab=current_cha_lab,
        current_def_lab=current_def_lab,
    )


if __name__ == "__main__":
    app.run(debug=True)
