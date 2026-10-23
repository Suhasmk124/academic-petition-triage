
from typing import TypedDict, Literal

from langgraph.graph import StateGraph, START, END
from retrieval import search_regulations


# --------------------------------------------------
# 1. WORKFLOW STATE
# --------------------------------------------------

class PetitionState(TypedDict):
    petition: str
    evidence: str
    assessment: str
    verification: str
    searches: int
    status: str


# --------------------------------------------------
# 2. INVESTIGATION AGENT
# --------------------------------------------------

def investigate(state: PetitionState) -> dict:
    """Retrieve relevant academic regulations for a petition."""

    query = state["petition"]

    # Use a more focused query if the first search was insufficient.
    if state["searches"] > 0:
        query = (
            "Find exact academic handbook clauses, attendance rules, "
            "medical condonation requirements, CMO certificates, "
            "and application deadlines relevant to: "
            + state["petition"]
        )

    evidence = search_regulations.invoke({"query": query})

    return {
        "evidence": evidence,
        "searches": state["searches"] + 1,
        "assessment": (
            "Preliminary assessment only. Identify the applicable rule, "
            "requirements, exceptions, and missing information. "
            "Do not make a final administrative decision."
        ),
    }


# --------------------------------------------------
# 3. EVIDENCE VERIFICATION
# --------------------------------------------------

def check_attendance_evidence(evidence: str) -> tuple[bool, list[str]]:
    """
    Basic keyword checks for the attendance-petition example.
    These checks do not prove that every claim is supported.
    """

    text = evidence.lower()
    missing = []

    if "80%" not in text:
        missing.append(
            "The 80% attendance threshold was not retrieved."
        )

    if "condoned" not in text or "medical" not in text:
        missing.append(
            "The medical-condonation provision was not retrieved."
        )

    if "cmo" not in text:
        missing.append(
            "The CMO medical-certificate requirement was not retrieved."
        )

    return len(missing) == 0, missing


def verify(state: PetitionState) -> dict:
    """Check whether the retrieved evidence contains required information."""

    evidence = state["evidence"]

    # Check for missing retrieval results.
    if (
        not evidence.strip()
        or "NO_SUFFICIENT_EVIDENCE" in evidence
        or "NO_EVIDENCE" in evidence
    ):
        if state["searches"] < 2:
            return {
                "verification": (
                    "Insufficient evidence. A focused retry is required."
                ),
                "status": "RETRY",
            }

        return {
            "verification": (
                "Evidence remained insufficient after two searches. "
                "Human review is required."
            ),
            "status": "ESCALATE",
        }

    # Perform the required attendance-evidence checks.
    passed, missing = check_attendance_evidence(evidence)

    if not passed:
        message = "Required evidence checks failed: " + " ".join(missing)

        if state["searches"] < 2:
            return {
                "verification": message,
                "status": "RETRY",
            }

        return {
            "verification": (
                message + " Human review is required."
            ),
            "status": "ESCALATE",
        }

    return {
        "verification": (
            "Required attendance evidence checks passed. "
            "The retrieved text includes the attendance threshold, "
            "medical-condonation provision, and CMO requirement. "
            "Individual claims and citations still require detailed "
            "verification. No final administrative decision was made."
        ),
        "status": "REVIEW_REQUIRED",
    }


# --------------------------------------------------
# 4. ROUTING AND RETRY CONTROL
# --------------------------------------------------

def route_after_verification(
    state: PetitionState,
) -> Literal["investigate", "finish"]:
    """Retry once when required evidence checks fail."""

    if state["status"] == "RETRY" and state["searches"] < 2:
        return "investigate"

    return "finish"


# --------------------------------------------------
# 5. BUILD LANGGRAPH WORKFLOW
# --------------------------------------------------

builder = StateGraph(PetitionState)

builder.add_node("investigate", investigate)
builder.add_node("verify", verify)

builder.add_edge(START, "investigate")
builder.add_edge("investigate", "verify")

builder.add_conditional_edges(
    "verify",
    route_after_verification,
    {
        "investigate": "investigate",
        "finish": END,
    },
)

app = builder.compile()


# --------------------------------------------------
# 6. TEST THE WORKFLOW
# --------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    petition = (
        "My attendance is 72%. I missed classes because of a medical issue. "
        "What does the handbook say about attendance condonation and "
        "required medical evidence?"
    )

    initial_state: PetitionState = {
        "petition": petition,
        "evidence": "",
        "assessment": "",
        "verification": "",
        "searches": 0,
        "status": "STARTED",
    }

    result = app.invoke(initial_state)

    print("\n" + "=" * 60)
    print("ACADEMIC PETITION TRIAGE RESULT")
    print("=" * 60)

    print("\nPETITION:")
    print(result["petition"])

    print("\nSTATUS:")
    print(result["status"])

    print("\nSEARCHES PERFORMED:")
    print(result["searches"])

    print("\nPRELIMINARY ASSESSMENT:")
    print(result["assessment"])

    print("\nVERIFICATION:")
    print(result["verification"])

    print("\nRETRIEVED EVIDENCE:")
    print(result["evidence"])

    print("\n" + "=" * 60)

