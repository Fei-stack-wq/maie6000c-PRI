"""Small English rule baseline. Return spans in the untouched review text."""
import re


PATTERNS = {
    "quality": (
        r"\b(?:broken|broke|defective|faulty|damaged|torn|stuck|jammed)\b",
        r"\b(?:fell|falls|falling|came|comes|coming)\s+apart\b",
        r"\b(?:poor|low|bad)\s+quality\b",
        r"\b(?:does\s+not|doesn['’]t|stopped)\s+work(?:ing)?\b",
        r"\b(?:zipper|zip|stitching|seam|strap)\b[^.!?;\n]{0,30}\b(?:broke|breaks|loose|split|jams|fails)\b",
    ),
    "logistics": (
        r"\b(?:delivery|shipping|shipment|package|parcel|order)\b[^.!?;\n]{0,45}"
        r"\b(?:tak(?:e|es|ing)|took|taken)\s+(?:way\s+|far\s+)?too\s+long\b",
        r"\b(?:delivery|shipping|shipment|package|parcel|order)\b[^.!?;\n]{0,45}"
        r"\b(?:tak(?:e|es|ing)|took|taken)\s+(?:forever|ages)\b",
        r"\b(?:tak(?:e|es|ing)|took|taken)\s+(?:way\s+|far\s+)?too\s+long\s+to\s+"
        r"(?:arrive|deliver|ship|receive)\b",
        r"\b(?:delivery|shipping|shipment|package|parcel|order)\b[^.!?;\n]{0,45}"
        r"\b(?:longer|slower)\s+than\s+(?:expected|promised|advertised)\b",
        r"\b(?:arrived|delivered)\b[^.!?;\n]{0,25}"
        r"\blater\s+than\s+(?:expected|promised|advertised)\b",
        r"\b(?:package|parcel|order|delivery|shipment)\b[^.!?;\n]{0,25}\boverdue\b",
        r"\b(?:have\s+not|haven['’]t|has\s+not|hasn['’]t|did\s+not|didn['’]t|never)\s+"
        r"(?:yet\s+)?(?:received?|got|get)\s+(?:(?:my|our|the|this)\s+)?"
        r"(?:order|package|parcel|delivery|item|product|it)\b",
        r"\b(?:have\s+not|haven['’]t|has\s+not|hasn['’]t|did\s+not|didn['’]t|not|never)\s+"
        r"(?:still\s+|yet\s+|been\s+)*(?:arrive[ds]?|delivered|shown\s+up)\b"
        r"(?!\s+(?:(?:very|too|that|so)\s+)?(?:late|early|damaged|broken|slowly)\b)",
        r"\b(?:have|has)\s+yet\s+to\s+(?:receive|get)\s+(?:(?:my|our|the|this)\s+)?"
        r"(?:order|package|parcel|delivery|item|product|it)\b",
        r"\bstill\s+waiting\s+for\s+(?:(?:my|our|the|this)\s+)?"
        r"(?:order|package|parcel|delivery|shipment|it)\b",
        r"\bwaiting\b[^.!?;\n]{0,35}\bfor\s+(?:weeks|months|too\s+long|ages)\b",
        r"\b(?:late|slow|delayed)\s+(?:delivery|shipping|shipment)\b",
        r"\b(?:delivery|shipping|shipment)\b[^.!?;\n]{0,35}\b(?:late|slow|delayed)\b",
        r"\b(?:arrived|delivered)\b[^.!?;\n]{0,20}\blate\b",
        r"\b(?:package|parcel|order)\b[^.!?;\n]{0,20}\b(?:missing|lost)\b",
    ),
    "mismatch": (
        r"\bwrong\s+(?:size|colou?r|item|product)\b",
        r"\bnot\s+as\s+(?:described|pictured|advertised|shown)\b",
        r"\b(?:colou?r|size|item|product)\b[^.!?;\n]{0,20}\bdifferent\b",
        r"\bdifferent\s+(?:colou?r|size|item|product)\b",
        r"\b(?:does\s+not|doesn['’]t)\s+match\b",
    ),
    "usability": (
        r"\b(?:uncomfortable|unusable)\b",
        r"\btoo\s+(?:heavy|tight|small|narrow)\b",
        r"\b(?:hard|difficult)\s+to\s+(?:use|carry|open|close|wear)\b",
        r"\bnot\s+enough\s+(?:space|room|capacity)\b",
        r"\b(?:not|isn['’]t|aren['’]t)\s+(?:very\s+)?comfortable\b",
        r"\b(?:does\s+not|doesn['’]t|cannot|can['’]t)\s+fit\b",
    ),
}
RULES = {category: tuple(re.compile(p, re.I) for p in patterns)
         for category, patterns in PATTERNS.items()}
POSITIVE = re.compile(
    r"\b(?:no\s+(?:issues?|problems?|defects?)|"
    r"works?\s+(?:(?:really|very)\s+)?(?:well|fine|perfectly)|"
    r"(?:great|excellent|good|perfect)\s+(?:bag|backpack|product|quality)|"
    r"(?:love|loved|like)\s+(?:it|this\s+(?:bag|backpack|product))|"
    r"(?:not|isn['’]t)\s+(?:broken|damaged|defective|uncomfortable)|"
    r"(?:does\s+not|doesn['’]t)\s+(?:get\s+)?stuck|"
    r"(?:arrived|delivered)\s+on\s+time|as\s+described|comfortable)\b|"
    r"^\s*(?:good|great|excellent|perfect|fine)[.!\s]*$", re.I,
)
CONTRAST = re.compile(r"\b(?:but|however|except|yet|although)\b|[.!?;。！？；\n]", re.I)
NEGATION = re.compile(
    r"\b(?:not|never|no|isn['’]t|aren['’]t|wasn['’]t|weren['’]t|doesn['’]t|don['’]t|"
    r"hasn['’]t|haven['’]t|hadn['’]t|didn['’]t)"
    r"(?:\s+(?:at|all|a|an|so|really|actually|very|ever|get|gets|getting|feel|feels|seem|seems|"
    r"taking|take|takes|taken|too|longer|slower|than|arrive|arrived|received|been|delivered))*\s*$",
    re.I,
)
UNCERTAIN = re.compile(
    r"\b(?:but|however|except|yet|although|maybe|unsure|strange|smells?|disappointed)\b|"
    r"\bnot\s+sure\b", re.I,
)


def _negated(text: str, start: int) -> bool:
    prefix = CONTRAST.split(text[:start])[-1]
    return NEGATION.search(prefix) is not None


def _match_is_negated(text: str, match: re.Match) -> bool:
    if _negated(text, match.start()):
        return True
    # Negation is part of these problem phrases, e.g. "not as described".
    if re.match(r"(?:not|never|(?:does|have|has|had|did)\s+not|doesn['’]t|isn['’]t|aren['’]t|"
                r"hasn['’]t|haven['’]t|hadn['’]t|didn['’]t|cannot|can['’]t)\b",
                match.group(), re.I):
        return False
    last = re.search(r"\b\w+\b\W*$", match.group())
    return last is not None and _negated(text, match.start() + last.start())


def find_issue(text: str, category: str) -> tuple[int, int] | None:
    # Check matches separately so a negated sentence cannot hide a later complaint.
    matches = [match for rule in RULES.get(category, ()) for match in rule.finditer(text)
               if not _match_is_negated(text, match)]
    if not matches:
        return None
    first = min(matches, key=lambda match: match.start())
    return first.span()


def no_issue_verdict(text: str) -> str:
    """Unmatched English is unknown unless there is an explicit positive/no-issue cue."""
    if UNCERTAIN.search(text):
        return "unknown"
    positive = any(not _negated(text, m.start()) for m in POSITIVE.finditer(text))
    return "no" if positive else "unknown"
