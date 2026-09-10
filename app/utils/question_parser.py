import re

_Q_START = re.compile(r'^\s*(\d+)[\.\)]\s*(.*)$')
_OPTION = re.compile(r'^\s*([A-Da-d])[\.\)]\s*(.*)$')
_ANSWER = re.compile(r'^\s*answer\s*:\s*(.*)$', re.IGNORECASE)
_MARKS = re.compile(r'^\s*marks?\s*:\s*([\d.]+)', re.IGNORECASE)
_SECTION = re.compile(
    r'^\s*section\s+([A-Za-z0-9]+)\b[:\-]?\s*(?:\[?\s*([\d.]+)\s*marks?\s*(?:each)?\s*\]?)?\s*$',
    re.IGNORECASE,
)


def parse_pasted_questions(raw_text, default_marks=1):
    """Turn a block of pasted exam questions into structured question dicts.

    Expected format (numbering and 'Answer:' are what drive detection —
    everything else is forgiving of extra spacing/blank lines):

        1. What is the powerhouse of the cell?
        A. Nucleus
        B. Mitochondria
        C. Ribosome
        D. Golgi apparatus
        Answer: B

        2. Explain the water cycle in your own words.
        Marks: 10
        Answer: Should mention evaporation, condensation, precipitation.

    Optional section headers bulk-set the mark value for every question
    under them, so a teacher can paste one exam with several sections
    scored differently:

        SECTION A [2 marks each]
        1. ...

        SECTION B [10 marks each]
        2. ...

    Marks precedence per question: an explicit "Marks:" line on that
    question > the enclosing section's bulk mark value > default_marks
    (the fallback passed in from the "score for questions with no
    explicit mark" field on the paste form).

    A question with A/B/C/D lines becomes multiple-choice; a question
    without them becomes a theory question, and its "Answer:" line (if
    not a single A-D letter) becomes the marking guide instead of the
    correct option.

    Returns a list of dicts: {prompt, type, marks, options, marking_guide, section}
    """
    lines = raw_text.replace("\r\n", "\n").split("\n")
    questions = []
    current = None
    current_section = None
    current_default_marks = default_marks

    def new_question(prompt_text):
        return {
            "prompt": prompt_text.strip(),
            "options": [],  # list of {"label": "A", "text": "..."}
            "answer_letter": None,
            "marks": current_default_marks,
            "marking_guide": "",
            "section": current_section,
        }

    def flush():
        nonlocal current
        if current and current["prompt"].strip():
            current["type"] = "mcq" if current["options"] else "theory"
            questions.append(current)
        current = None

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue

        m_section = _SECTION.match(line)
        if m_section:
            flush()
            current_section = m_section.group(1).upper()
            if m_section.group(2):
                current_default_marks = float(m_section.group(2))
            continue

        m_q = _Q_START.match(line)
        if m_q:
            flush()
            current = new_question(m_q.group(2))
            continue

        if current is None:
            # Pasted text didn't start with "1." — treat the first
            # non-empty line as the start of question 1 anyway.
            current = new_question(line)
            continue

        m_opt = _OPTION.match(line)
        if m_opt:
            current["options"].append({"label": m_opt.group(1).upper(), "text": m_opt.group(2).strip()})
            continue

        m_ans = _ANSWER.match(line)
        if m_ans:
            value = m_ans.group(1).strip()
            if len(value) == 1 and value.upper() in "ABCD":
                current["answer_letter"] = value.upper()
            else:
                current["marking_guide"] = (current["marking_guide"] + " " + value).strip()
            continue

        m_marks = _MARKS.match(line)
        if m_marks:
            current["marks"] = float(m_marks.group(1))
            continue

        # Plain continuation line — extends the prompt if we haven't hit
        # options yet, otherwise extends the marking guide (theory answers
        # that span multiple lines).
        if current["options"]:
            current["marking_guide"] = (current["marking_guide"] + " " + line.strip()).strip()
        else:
            current["prompt"] = (current["prompt"] + " " + line.strip()).strip()

    flush()
    return questions
