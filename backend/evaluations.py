"""
Where to get properly assessed, and what to avoid.

The in-app screener already says it is not a clinical test and points at a real
neuropsychological evaluation as better evidence. This is the other half of
that sentence: who actually does one, what instruments they use, and what it
costs.

Two editorial rules shape the list.

First, the distinction that matters is SCREENING versus ASSESSMENT. A free
self-report questionnaire can tell you it is worth asking someone; it cannot
tell you what your working memory is. Anything here that is self-report says so
in its own row, rather than in a footnote nobody reads.

Second, learning-styles inventories are listed under what to AVOID, not under
what to try. The app refuses to make learning-style claims anywhere else - the
visual routing this app does is driven by a measured gap between a person's
own visual and auditory span, not by a personality type - so recommending
a questionnaire that sells a "learner type" would contradict the thing the whole
tool is built on.

No endorsement of any individual clinician is implied or possible. These are
professional bodies and directories, which is as specific as anyone should get
without knowing the person.
"""

from __future__ import annotations

# --------------------------------------------------------------- the real thing

FORMAL = {
    "heading": "A full neuropsychological evaluation",
    "what": (
        "The thing that produces scores this app can actually use. A clinical "
        "neuropsychologist administers a battery over one or more sessions and "
        "writes a report with norm-referenced index and subtest scores, plus "
        "recommendations you can take to a disability office."
    ),
    "instruments": [
        {"name": "WAIS-5", "measures": "General cognitive ability, including "
                                       "working memory and processing speed"},
        {"name": "WMS-IV", "measures": "Memory - immediate, delayed, visual and auditory"},
        {"name": "D-KEFS", "measures": "Executive function: inhibition, switching, "
                                       "verbal fluency, planning"},
        {"name": "WIAT-4 or WJ-IV", "measures": "Academic achievement - reading, "
                                                "writing, maths, against grade norms"},
        {"name": "CTOPP-2", "measures": "Phonological processing, when dyslexia is a question"},
        {"name": "Nelson-Denny", "measures": "Reading rate and comprehension - "
                                             "often requested for extended-time requests"},
    ],
    "caveats": [
        "Cost varies enormously by country and payer. In the US privately it is "
        "commonly four figures; through a university or a public health system "
        "it may be far less or free.",
        "Waiting lists are real. If the goal is accommodations for a specific "
        "exam, start months ahead, not weeks.",
        "A report is only as useful as its recommendations. Ask explicitly for "
        "functional recommendations, not just scores.",
    ],
}

WHERE = [
    {
        "name": "Your university's disability or accessibility office",
        "url": "",
        "why": (
            "The correct first stop for any enrolled student, and usually the "
            "cheapest. Many schools fund or subsidise assessment, keep referral "
            "lists, and are the office that must approve accommodations anyway."
        ),
        "kind": "first stop",
    },
    {
        "name": "APA Psychologist Locator",
        "url": "https://locator.apa.org",
        "why": "The American Psychological Association's directory. Filter by "
               "speciality to find assessment and neuropsychology.",
        "kind": "directory",
    },
    {
        "name": "American Academy of Clinical Neuropsychology",
        "url": "https://theaacn.org",
        "why": "Find a board-certified clinical neuropsychologist (ABPP-CN). "
               "Board certification is a meaningful filter here.",
        "kind": "directory",
    },
    {
        "name": "National Academy of Neuropsychology",
        "url": "https://nanonline.org",
        "why": "Another professional body with a find-a-provider function and "
               "plain-language explanations of what an evaluation involves.",
        "kind": "directory",
    },
    {
        "name": "British Psychological Society",
        "url": "https://www.bps.org.uk",
        "why": "For the UK - the Directory of Chartered Psychologists.",
        "kind": "directory",
    },
]

ACCOMMODATIONS = {
    "heading": "If the goal is test accommodations",
    "points": [
        {
            "name": "USMLE test accommodations",
            "url": "https://www.usmle.org/test-accommodations",
            "why": "Documentation requirements and deadlines are published and "
                   "strict. Read them BEFORE booking an evaluation, so the "
                   "assessment covers what they actually ask for.",
        },
        {
            "name": "Your own school's student accessibility office",
            "url": "",
            "why": "School accommodations and board accommodations are separate "
                   "applications with separate criteria. Having one does not "
                   "grant the other.",
        },
    ],
}

# ------------------------------------------------------- free, honest screeners

SCREENERS = [
    {
        "name": "ASRS-v1.1 (Adult ADHD Self-Report Scale)",
        "url": "https://www.hcp.med.harvard.edu/ncs/asrs.php",
        "what": "Six-question screener developed with the World Health Organization. "
                "Free, takes two minutes.",
        "limit": "SCREENING ONLY. A positive result is a reason to seek an "
                 "assessment. It is not a diagnosis and produces no scores this "
                 "app can use.",
    },
    {
        "name": "This app's own screener",
        "url": "",
        "what": "Four short tasks comparing your own results against each other "
                "to decide how material should be presented to you.",
        "limit": "Not a clinical test. No IQ, no percentile, no norm comparison. "
                 "If you have had a real evaluation, enter those scores instead.",
    },
]

# ------------------------------------------------------------------ what to skip

AVOID = {
    "heading": "What to skip, and why",
    "items": [
        {
            "name": "Learning-styles inventories (VARK, Kolb LSI, Honey & Mumford)",
            "why": (
                "These sort you into a visual, auditory or kinaesthetic learner. "
                "Reviews that looked for the effect - Pashler and colleagues in "
                "2008, Willingham and colleagues in 2015 - did not find that "
                "matching teaching to a self-reported style improves learning. "
                "This app deliberately makes no learning-style claim, so it will "
                "not send you to a questionnaire that sells one."
            ),
        },
        {
            "name": "\"Left brain / right brain\" and multiple-intelligence quizzes",
            "why": "Same problem: a memorable label with no evidence that acting "
                   "on it changes outcomes.",
        },
        {
            "name": "Paid online \"cognitive assessments\" that produce a report "
                    "without a clinician",
            "why": "A disability office and a licensing board will not accept "
                   "them, which is usually the entire reason for testing.",
        },
    ],
}

# --------------------------------------------- what actually helps, for free

EVIDENCE = {
    "heading": "Free and actually evidence-based",
    "items": [
        {
            "name": "Dunlosky et al. (2013), Improving Students' Learning With "
                    "Effective Learning Techniques",
            "url": "https://journals.sagepub.com/doi/10.1177/1529100612453266",
            "why": (
                "Ten study techniques rated for utility. Practice testing and "
                "distributed practice came out high; highlighting, rereading and "
                "summarising came out low. This app is built on those ratings - "
                "it is why everything here is retrieval practice on a schedule "
                "rather than review."
            ),
        },
        {
            "name": "Your own error log",
            "url": "",
            "why": "The Mastery map and How-you-learn tabs are this. What you get "
                   "wrong, grouped, is better evidence about your studying than "
                   "any questionnaire about your studying.",
        },
    ],
}


def payload() -> dict:
    return {
        "formal": FORMAL,
        "where": WHERE,
        "accommodations": ACCOMMODATIONS,
        "screeners": SCREENERS,
        "avoid": AVOID,
        "evidence": EVIDENCE,
        "disclaimer": (
            "Learnometry is a study tool, not a clinician. Nothing here is "
            "medical advice, and no individual provider is endorsed - these are "
            "professional bodies and directories to start from."
        ),
    }
