import json
import re
from html import escape
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st
import xml.etree.ElementTree as ET


DESIGNATION_CANONICAL = {
    "plaintiff": "Plaintiff",
    "plaintiffs": "Plaintiffs",
    "defendant": "Defendant",
    "defendants": "Defendants",
    "appellant": "Appellant",
    "appellants": "Appellants",
    "appellee": "Appellee",
    "appellees": "Appellees",
    "petitioner": "Petitioner",
    "petitioners": "Petitioners",
    "respondent": "Respondent",
    "respondents": "Respondents",
    "amicus": "Amicus",
    "amici": "Amici",
    "mediator": "Mediator",
    "mediators": "Mediators",
    "special master": "Special Master",
    "special masters": "Special Masters",
    "arbitrator": "Arbitrator",
    "arbitrators": "Arbitrators",
    "expert witness": "Expert Witness",
    "expert witnesses": "Expert Witnesses",
}

SPECIALIZED_ROLES = {
    "mediator",
    "special master",
    "arbitrator",
    "expert witness",
}

STATUS_REMOVE_PATTERNS = [
    r"\bLEAD ATTORNEY\b",
    r"\bATTORNEY TO BE NOTICED\b",
    r"\bCJA APPOINTMENT\b",
    r"\bRETAINED\b",
    r"\bPRO BONO\b",
]

TITLE_SPLIT_OR = re.compile(r"\s+or\s+", flags=re.IGNORECASE)
TITLE_VERSUS = re.compile(r"\s+(?:v\.|vs\.?|versus)\s+", flags=re.IGNORECASE)
TITLE_AND = re.compile(r"\s+and\s+", flags=re.IGNORECASE)

RETAINED_STATUS_TITLES = [
    "Pro Hac Vice",
    "Public Defender",
    "Federal Public Defender",
    "AUSA",
    "Assistant U.S. Attorney",
    "U.S. Attorney",
    "United States Attorney",
    "Government Attorney",
]

PROTECTED_CAPS = {
    "llc": "LLC",
    "l.l.c.": "L.L.C.",
    "llp": "LLP",
    "l.l.p.": "L.L.P.",
    "pllp": "PLLP",
    "p.l.l.p.": "P.L.L.P.",
    "pllc": "PLLC",
    "p.l.l.c.": "P.L.L.C.",
    "pc": "PC",
    "p.c.": "P.C.",
    "pa": "PA",
    "p.a.": "P.A.",
    "fsb": "FSB",
    "fbt": "FBT",
    "fcc": "FCC",
    "plc": "PLC",
    "doj": "DOJ",
    "doj-usao": "DOJ",
    "usao": "USAO",
    "sec": "SEC",
    "snmcf": "SNMCF",
    "u.s": "U.S",
    "usa": "USA",
    "us": "US",
    "inc": "Inc.",
    "inc.": "Inc.",
    "ltd": "Ltd.",
    "ltd.": "Ltd.",
    "corp": "Corp.",
    "corp.": "Corp.",
}

STATUS_CANONICAL = {
    "cor": "Cor",
    "ld": "Ld",
    "ntc": "Ntc",
    "attorney general": "Attorney General",
    "attorneys general": "Attorneys General",
    "district attorney": "District Attorney",
    "att ys.gen.": "Attys.Gen.",
    "attys.gen.": "Attys.Gen.",
    "asst.atty.gen.": "Asst.Atty.Gen.",
    "assistant attorney general": "Assistant Attorney General",
    "special assistant attorney general": "Special Assistant Attorney General",
}

SENSITIVE_NUMBER_PATTERNS = (
    (re.compile(r"(\b(?:SSN|Social Security Number)\s*:\s*)\d[\d\- ]*", re.I), r"\1XXX-XX-XXXX"),
    (re.compile(r"(\b(?:Bank Account #|Bank Account Number)\s*:\s*)\d[\d\- ]*", re.I), r"\1XXXXXXXXXX"),
    (re.compile(r"(\b(?:ARN|I&NS No\.?|INS Nos?\.?|Alien File #|USCIS File No\.?|BIA No\.?)\s*:?[ ]*)[A-Z0-9\-– ]+", re.I), r"\1AXX-XX1-234"),
    (re.compile(r"(\b(?:Employer Identification Number \(EIN\)|Tax ID Number \(TIN\))\s*)[\d\- ]+", re.I), r"\1XXX-XX-XXXX"),
)


@dataclass
class Attorney:
    name: str
    status: str
    firm: str
    street: str
    city: str
    state: str
    phone: str
    is_pro_se: bool


@dataclass
class Party:
    party_type: str
    name: str
    attorneys: List[Attorney]
    descriptions: List[str]


def text_of(node: Optional[ET.Element]) -> str:
    if node is None:
        return ""
    txt = "".join(node.itertext()).strip()
    return re.sub(r"\s+", " ", txt)


def redact_sensitive_numbers(value: str) -> str:
    """Apply VC redaction examples before source values enter output."""
    result = value or ""
    for pattern, replacement in SENSITIVE_NUMBER_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def parse_mmddyyyy(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def terminated_within_one_year(terminated_value: str, today: Optional[date] = None) -> bool:
    t = parse_mmddyyyy(terminated_value)
    if not t:
        return False
    today = today or date.today()
    return (today - timedelta(days=365)) <= t <= today


def normalize_name_for_match(name: str) -> str:
    n = (name or "").lower()
    n = n.replace("u.s.", "united states").replace("u.s", "united states")
    n = n.replace("usa", "united states")
    n = re.sub(r"\bsec\b", "securities and exchange commission", n)
    n = re.sub(r"\bus\b", "united states", n)
    n = re.sub(r"\bthe\b", " ", n)
    n = re.sub(r"\bof\b", " ", n)
    n = re.sub(r"\bllc\b|\bllp\b|\binc\b|\bcorp\b|\bcorporation\b", " ", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def names_equivalent(a: str, b: str) -> bool:
    na = normalize_name_for_match(a)
    nb = normalize_name_for_match(b)
    return na == nb or na in nb or nb in na


def normalize_caps(value: str) -> str:
    """Full normalization per .txt Part II: title case, period initials, abbreviations, location prefixes."""
    v = redact_sensitive_numbers((value or "").strip())
    if not v:
        return ""
    
    # If all uppercase, title-case ordinary words while preserving only
    # recognized legal/entity abbreviations and suffixes.
    if v.isupper() or any(
        token.strip(".,;:()[]") .isupper()
        and len(token.strip(".,;:()[]")) > 1
        for token in v.split()
    ):
        parts = []
        for token in v.split():
            leading = re.match(r"^[^A-Za-z0-9]*", token).group(0)
            trailing = re.search(r"[^A-Za-z0-9]*$", token).group(0)
            core = token[len(leading):len(token) - len(trailing) or None]
            if not core:
                parts.append(token)
                continue
            if core.lower() in PROTECTED_CAPS:
                normalized = PROTECTED_CAPS[core.lower()]
                if trailing == "." and normalized.endswith("."):
                    trailing = ""
            elif v.isupper() or core.isupper():
                normalized = core.title()
            else:
                normalized = core
            parts.append(f"{leading}{normalized}{trailing}")
        v = " ".join(parts)
    
    # Location prefixes (St, Dr, etc.) with periods
    v = re.sub(r"\bSt\b", "St.", v)
    v = re.sub(r"\bDr\b", "Dr.", v)
    
    # Name initials with periods (e.g., "J Smith" → "J. Smith")
    v = re.sub(r"\b([A-Z])\s+([A-Z][a-z])", r"\1. \2", v)
    
    # Suffixes with periods: Jr, Sr, III, II, IV, etc.
    v = re.sub(r"\b(Jr|Sr)\b\.?", r"\1.", v)
    v = re.sub(r"\b(II|III|IV|V|VI|VII|VIII|IX)\b\.?", r"\1.", v)
    
    # Standardize "United States" vs "US"
    v = re.sub(r"\bUS(?=\s|$)", "United States", v)
    # Preserve source U.S. acronym; only standalone US is expanded.
    v = re.sub(r"\b(United States)\.\s+(?=[A-Z])", r"\1 ", v)
    v = re.sub(r"([A-Za-z])'S\b",
               lambda match: f"{match.group(1)}'s", v, flags=re.IGNORECASE)
    v = re.sub(r"([A-Za-z])'s\.", r"\1's", v)
    
    return re.sub(r"\s+", " ", v).strip()


def clean_attorney_status(raw_status: str) -> str:
    """Clean status with retained-title precedence per .txt Part III, Step 3."""
    s = redact_sensitive_numbers((raw_status or "").strip())
    if not s:
        return ""

    # Remove known phrases
    for pat in STATUS_REMOVE_PATTERNS:
        s = re.sub(pat, "", s, flags=re.IGNORECASE)
    # COR/NTC values are internal notice codes, not display titles.
    s = re.sub(r"\bCOR(?:\s+LD)?\s+NTC\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*;\s*", "; ", s)
    s = re.sub(r"\s+", " ", s).strip("; ")

    if not s:
        return ""

    # Split on ; , / to get candidates
    candidates = [x.strip() for x in re.split(r"[;,/]", s) if x.strip()]
    normalized_candidates: List[str] = []
    
    for c in candidates:
        # For "X or Y" patterns, take only the first (X)
        c = TITLE_SPLIT_OR.split(c)[0].strip()
        
        # Preserve source abbreviations and normalize only known status forms.
        status_key = re.sub(r"\s+", " ", c).strip().lower()
        if status_key in STATUS_CANONICAL:
            normalized_candidates.append(STATUS_CANONICAL[status_key])
            continue

        # Normalize known title patterns
        c = re.sub(r"\bAssistant\s+US\s+Attorney\b", "Assistant U.S. Attorney", c, flags=re.IGNORECASE)
        c = re.sub(r"\bUnited\s+States\s+Attorney\b", "United States Attorney", c, flags=re.IGNORECASE)
        c = re.sub(r"\bUS\s+Attorney\b", "U.S. Attorney", c, flags=re.IGNORECASE)
        c = re.sub(r"\bGovt\.?\s+Attorney\b", "Government Attorney", c, flags=re.IGNORECASE)
        c = re.sub(r"\bPublic\s+Defender\b", "Public Defender", c, flags=re.IGNORECASE)
        
        # Handle acronyms
        if c.upper() in {"AUSA", "DOJ", "FSB", "PLC", "LLC", "PC", "PA", "US ATTORNEY", "U.S. ATTORNEY"}:
            c = c.upper()
        elif c.isupper():
            c = c.title()
        
        normalized_candidates.append(c)

    if not normalized_candidates:
        return ""

    # Retained-title precedence: check in order and return first match
    for keep in RETAINED_STATUS_TITLES:
        for c in normalized_candidates:
            if c.lower() == keep.lower():
                return keep

    # Default: return first candidate
    return normalized_candidates[0].strip()


def normalize_firm_name(firm: str) -> str:
    """Normalize firm per .txt Part II: standardize punctuation, handle legal suffixes."""
    raw = (firm or "").strip()
    if re.fullmatch(r"DOJ\s*[-/]\s*USAO", raw, flags=re.IGNORECASE):
        return "DOJ-United States Attorney's Office"
    raw = re.sub(
        r"\b(?:Office\s+of\s+the\s+)?(?:U\.?S\.?|United\s+States)\s+Attorney(?:'s\s+Office|\s+Office)?\b",
        "DOJ-United States Attorney's Office",
        raw,
        flags=re.IGNORECASE,
    )
    f = normalize_caps(raw)
    if normalize_name_for_match(f) in {"doj usao", "usao"}:
        return "DOJ-United States Attorney's Office"
    if not f:
        return ""
    
    # Preserve legal-suffix punctuation and commas exactly as supplied in XML.
    
    # Remove location suffix (state/city at end): "Firm, City, ST" → "Firm"
    f = re.sub(r"\s*,\s*[A-Z][a-z]+\s*,\s*[A-Z]{2}\s*$", "", f)
    
    # Remove trailing state abbreviation: "Firm, ST" → "Firm"
    f = re.sub(r"\s*-\s*[A-Z]{2,}$", "", f)
    f = re.sub(r"\s*\([A-Z]{2,}\)$", "", f)
    
    # Normalize every United States Attorney's Office spelling.
    f = re.sub(
        r"\b(?:Office\s+of\s+the\s+)?(?:U\.?S\.?|United\s+States)\s+Attorney(?:'s\s+Office|\s+Office|\s+Office)?\b",
        "DOJ-United States Attorney's Office",
        f,
        flags=re.IGNORECASE,
    )
    f = f.replace("DOJ-DOJ-", "DOJ-")
    f = re.sub(r"\bOffice\s+of\s+the\s+Attorney\s+General(?:\s+for\s+the\s+State\s+of\s+[A-Za-z ]+)?\b",
               "Office of the Attorney General", f, flags=re.IGNORECASE)
    if "attorney general" in f.lower():
        f = "Office of the Attorney General"
    
    f = re.sub(r"\s+", " ", f).strip(" ,")
    f = re.sub(r"^(?:DOJ-)+", "DOJ-", f)
    return f


def looks_like_org_in_street(street: str) -> bool:
    s = (street or "").lower()
    return any(tok in s for tok in [
        "llp", "llc", "law", "office", "department", "commission",
        "attorney", "doj", "usao", "federal",
    ])


def extract_address_streets(attorney_block: ET.Element) -> tuple[str, str]:
    """Return firm/agency line and physical street from address blocks."""
    nodes = attorney_block.findall(".//attorney.address.block/street")
    if not nodes:
        nodes = attorney_block.findall(".//firm.address.block/street")
    values = []
    for node in nodes:
        raw = text_of(node)
        if not raw:
            continue
        if re.fullmatch(r"DOJ\s*[-/]\s*USAO", raw, flags=re.IGNORECASE):
            values.append("DOJ-United States Attorney's Office")
        else:
            values.append(normalize_caps(raw))
    if len(values) >= 2:
        # Novus commonly places the firm or agency on the first street line,
        # followed by the postal street/suite lines.
        return values[0], ", ".join(values[1:])
    if values and looks_like_org_in_street(values[0]):
        return values[0], ""
    return "", values[0] if values else ""


def canonical_party_type(raw_type: str) -> str:
    """Extract base party type, handling hybrid types like 'Plaintiff - Appellee'."""
    t = normalize_caps(raw_type)
    
    # Handle hybrid types: "Plaintiff - Appellee" → extract "Plaintiff"
    if " - " in t or " -" in t or "- " in t:
        parts = re.split(r"\s*-\s*", t)
        t = parts[0].strip()
    
    tl = t.lower()
    
    # Check for each designation type
    if "amic" in tl:
        return "Amicus"
    if "appellant" in tl:
        return "Appellant" if "appellants" not in tl else "Appellants"
    if "appellee" in tl:
        return "Appellee" if "appellees" not in tl else "Appellees"
    if "plaintiff" in tl:
        return "Plaintiff" if "plaintiffs" not in tl else "Plaintiffs"
    if "defendant" in tl:
        return "Defendant" if "defendants" not in tl else "Defendants"
    if "petitioner" in tl:
        return "Petitioner" if "petitioners" not in tl else "Petitioners"
    if "respondent" in tl:
        return "Respondent" if "respondents" not in tl else "Respondents"
    
    return t


def extract_title_text(root: ET.Element) -> str:
    """Extract title with fallback paths per .txt instructions."""
    candidate_paths = [
        ".//content.long.title",
        ".//primary.title",
        ".//md.title",
        ".//title.block",
    ]
    for path in candidate_paths:
        node = root.find(path)
        txt = text_of(node)
        if txt:
            txt = re.sub(r"^Case\s+Title:\s*", "", txt, flags=re.IGNORECASE)
            return txt
    return ""


def infer_jurisdiction(root: ET.Element) -> str:
    """Infer federal versus state address formatting from Novus metadata."""
    state_code = text_of(root.find('.//md.jurisstate')).upper()
    court = text_of(root.find('.//md.juriscourt')).lower()
    if state_code in {'FE', 'FEDERAL'} or 'federal' in court or 'circuit' in court:
        return 'federal'
    if state_code or court:
        return 'state'
    # Preserve the existing behavior for minimal XML fixtures that do not
    # carry jurisdiction metadata.
    return 'federal'


def normalize_title_connectors(title: str) -> str:
    """Apply the VC title-connector rules before party parsing.

    Source variants such as ``versus``, ``V.``, and ``vs.`` are represented as
    the canonical lowercase ``v.`` connector.  ``and`` is intentionally not
    rewritten here because it may be part of a party name; party splitting is
    handled only when the title also supplies a designation.
    """
    value = re.sub(r"\s+", " ", (title or "")).strip(" ,.;")
    value = re.sub(r"^Re:\s*", "", value, flags=re.IGNORECASE)
    value = TITLE_VERSUS.sub(" v. ", value)
    # VC rule: omit versus when it precedes an Ex Parte title.
    return re.sub(r"\s+v\.\s+(?=Ex\s+Parte\b)", " ", value, flags=re.IGNORECASE)


def parse_title_parties(title_text: str) -> Dict[str, dict]:
    """Parse title to extract parties with designations and et al. rules per .txt Part I."""
    result: Dict[str, dict] = {}
    if not title_text:
        return result

    body = normalize_title_connectors(title_text)
    side_chunks = TITLE_VERSUS.split(body)
    if len(side_chunks) == 1:
        side_chunks = [body]

    desig_pattern = re.compile(
        r"^(?P<names>.*?),\s*(?P<desig>Plaintiff\(s\)|Plaintiffs?|Defendant\(s\)|Defendants?|Appellant\(s\)|Appellants?|Appellee\(s\)|Appellees?|Petitioner\(s\)|Petitioners?|Respondent\(s\)|Respondents?|Amicus(?:\s+Curiae)?|Amici(?:\s+Curiae)?|Mediator\(s\)|Mediators?|Special\s+Master\(s\)|Special\s+Masters?|Arbitrator\(s\)|Arbitrators?|Expert\s+Witness(?:es)?)(?:\.|,)?$",
        flags=re.IGNORECASE,
    )

    for chunk in side_chunks:
        c = chunk.strip(" ,.;")
        m = desig_pattern.match(c)
        if not m:
            continue
        names_raw = m.group("names").strip()
        desig_raw = m.group("desig").strip()
        desig_key = re.sub(r"\(s\)", "", desig_raw, flags=re.IGNORECASE).lower()
        designation = DESIGNATION_CANONICAL.get(desig_key, normalize_caps(desig_raw))

        # et al. rule per .txt Part I
        has_et_al = bool(re.search(r"\bet\s+al\.?\b", names_raw, flags=re.IGNORECASE))
        names_raw = re.sub(r"\bet\s+al\.?\b", "", names_raw, flags=re.IGNORECASE)
        names_raw = re.sub(r",?\s+individually.*$", "", names_raw, flags=re.IGNORECASE)
        names_raw = re.sub(r",?\s+in\s+(?:his|her|their)\s+official\s+capacity.*$", "", names_raw, flags=re.IGNORECASE)
        names_raw = re.sub(r",?\s+as\s+[^,]+$", "", names_raw, flags=re.IGNORECASE)
        names_raw = re.sub(r",?\s+Wife\s+of\s+.*$", "", names_raw, flags=re.IGNORECASE)
        names_raw = names_raw.replace(";", ",")
        names_raw = re.sub(r",\s*(?=(?:Inc|Incorporated|LLC|LLP|PLLC|PC|P\.C\.|P\.A\.)\b)", "§", names_raw, flags=re.IGNORECASE)
        # In a designated caption, `and` joins distinct title segments. Do
        # not apply this transformation to fallback/no-designation titles.
        names_raw = TITLE_AND.sub(",", names_raw)
        output_names = [clean_caption_party_name(n.replace("§", ","))
                for n in names_raw.split(",") if n.strip(" .,;")]
        names = [normalize_caps(n) for n in output_names]

        key = designation.lower()
        result[key] = {
            "designation": designation,
            "names": names,
            "output_names": output_names,
            "has_et_al": has_et_al,
        }

    # Fallback for no-designation cases (US v. Defendant)
    if not result:
        has_et_al = bool(re.search(r"\bet\s+al\.?\b", body, flags=re.IGNORECASE))
        names: List[str] = []
        for chunk in side_chunks:
            c = chunk.strip(" ,.;")
            c = re.sub(r"\bet\s+al\.?\b", "", c, flags=re.IGNORECASE)
            c = c.strip(" ,.;")
            if c:
                names.append(normalize_caps(c))
        if names:
            result["__no_designation__"] = {
                "designation": "",
                "names": names,
                "has_et_al": has_et_al,
                "no_designation": True,
            }

    return result


def iter_party_elements(root: ET.Element) -> List[ET.Element]:
    parties = []
    for elem in root.iter():
        if elem.tag.endswith(".party"):
            if elem.find(".//party.type") is not None:
                parties.append(elem)
    return parties


def extract_party_name(party_elem: ET.Element) -> str:
    node = party_elem.find(".//party.name/cite.query")
    if node is not None and text_of(node):
        return normalize_caps(text_of(node))
    node2 = party_elem.find(".//party.name")
    return normalize_caps(text_of(node2))


def extract_party_descriptions(party_elem: ET.Element) -> List[str]:
    """Extract party descriptions (aka blocks) for matching per .txt."""
    descriptions: List[str] = []
    for aka in party_elem.findall(".//party.aka"):
        desc = text_of(aka)
        if desc:
            descriptions.append(normalize_caps(desc))
    return descriptions


def extract_attorneys_from_party(party_elem: ET.Element) -> List[Attorney]:
    """Extract attorneys with OIL exclusion, termination checks per .txt Part I."""
    attorneys: List[Attorney] = []
    for ab in party_elem.findall(".//party.attorney.block"):
        name = normalize_caps(text_of(ab.find(".//attorney.name/cite.query")) or text_of(ab.find(".//attorney.name")))
        name = re.sub(r"\s*,?\s+(?:Esq\.?|Esquire)$", "", name, flags=re.IGNORECASE).strip()

        # OIL attorney exclusion per .txt Part I
        if name and "oil" in name.lower():
            continue

        # Termination check: exclude if not within 1 year per .txt Part I
        at = text_of(ab.find(".//attorney.terminated.block/attorney.terminated")) or text_of(ab.find(".//attorney.terminated"))
        if at and not terminated_within_one_year(at):
            continue

        status = clean_attorney_status(text_of(ab.find(".//attorney.status")))
        is_pro_se = bool(re.search(r"\bpro\s*se\b", status, flags=re.IGNORECASE))

        firm = normalize_firm_name(text_of(ab.find(".//firm.name.block/firm.name")) or text_of(ab.find(".//firm.name")))
        address_firm, street = extract_address_streets(ab)
        if not firm:
            firm = normalize_firm_name(address_firm)
        city = normalize_caps(text_of(ab.find(".//firm.address.block/city")) or text_of(ab.find(".//attorney.address.block/city")))
        state = normalize_caps(text_of(ab.find(".//firm.address.block/state")) or text_of(ab.find(".//attorney.address.block/state")))
        phone = normalize_caps(
            text_of(ab.find(".//firm.address.block/phone"))
            or text_of(ab.find(".//attorney.address.block/phone"))
            or text_of(ab.find(".//attorney.phone"))
        )

        org = firm
        if not org and looks_like_org_in_street(street):
            org = street

        # Firm-only counsel is allowed
        if not name and not org:
            continue

        attorneys.append(
            Attorney(
                name=name,
                status=status,
                firm=org,
                street=street,
                city=city,
                state=state,
                phone=phone,
                is_pro_se=is_pro_se,
            )
        )
    return attorneys


def parse_parties(root: ET.Element) -> List[Party]:
    """Parse all parties from XML, excluding terminated parties per .txt Part I."""
    parties: List[Party] = []
    for party_elem in iter_party_elements(root):
        # Exclude terminated parties
        if party_elem.find(".//party.terminated.block") is not None:
            continue

        ptype = canonical_party_type(text_of(party_elem.find(".//party.type")))
        pname = extract_party_name(party_elem)
        if not pname:
            continue

        attorneys = extract_attorneys_from_party(party_elem)
        parties.append(Party(
            party_type=ptype,
            name=pname,
            attorneys=attorneys,
            descriptions=extract_party_descriptions(party_elem),
        ))
    return parties


def is_specialized_role(party_type: str) -> bool:
    return normalize_name_for_match(party_type) in {normalize_name_for_match(x) for x in SPECIALIZED_ROLES}


def pick_parties_for_output(all_parties: List[Party], title_info: Dict[str, dict]) -> List[Party]:
    """Select parties per .txt Part I: caption override, et al. rule, amicus always."""
    selected: List[Party] = []
    title_types = {normalize_name_for_match(v["designation"]) for v in title_info.values() if v.get("designation")}
    no_designation_rule = title_info.get("__no_designation__")

    # Always include amicus parties per .txt Part I
    amicus_parties = [p for p in all_parties if "amic" in p.party_type.lower()]

    for p in all_parties:
        ptype_key = normalize_name_for_match(p.party_type)
        
        # Exclude specialized roles not in caption per .txt Part I
        if is_specialized_role(p.party_type) and ptype_key not in title_types:
            continue

        # Always include amicus
        if "amic" in p.party_type.lower():
            selected.append(p)
            continue

        # No-designation case (US v. Defendant)
        if no_designation_rule is not None:
            if no_designation_rule.get("has_et_al"):
                selected.append(p)
                continue
            explicit_names = no_designation_rule.get("names", [])
            if any(names_equivalent(p.name, n) for n in explicit_names):
                selected.append(p)
            continue

        # Find matching caption entry for this party type
        matching_title_key = None
        for k, v in title_info.items():
            if normalize_name_for_match(v["designation"]) == ptype_key:
                matching_title_key = k
                break

        if not matching_title_key:
            continue

        rule = title_info[matching_title_key]
        
        # et al. rule: include all parties of this type per .txt Part I
        if rule.get("has_et_al"):
            selected.append(p)
            continue

        # Explicit name match per .txt Part I
        explicit_names = rule.get("names", [])
        if any(
            names_equivalent(p.name, n)
            or any(names_equivalent(description, n)
                   for description in p.descriptions)
            for n in explicit_names
        ):
            selected.append(p)

    # Ensure amicus parties are included
    for ap in amicus_parties:
        if ap not in selected:
            selected.append(ap)

    return selected


def attorney_signature(a: Attorney) -> Tuple[str, str, str, str, str]:
    return (
        normalize_name_for_match(a.name),
        normalize_name_for_match(a.status),
        normalize_name_for_match(a.firm),
        normalize_name_for_match(a.city),
        normalize_name_for_match(a.state),
    )


def party_attorney_set_signature(p: Party) -> Tuple[Tuple[str, str, str, str, str], ...]:
    sigs = sorted({attorney_signature(a) for a in p.attorneys})
    return tuple(sigs)


def pluralize_designation(designation: str, count: int) -> str:
    """Pluralize designation per .txt Part IV."""
    if count <= 1:
        if designation.endswith("s"):
            return designation[:-1]
        return designation
    if designation.lower() == "amici":
        return "Amici"
    if designation.lower() == "amicus":
        return "Amici"
    if designation.endswith("s"):
        return designation
    return designation + "s"


def clean_party_name_for_output(name: str) -> str:
    n = normalize_caps(name)
    n = re.sub(r",?\s+individually.*$", "", n, flags=re.IGNORECASE)
    n = re.sub(r",?\s+in\s+his\s+official\s+capacity.*$", "", n, flags=re.IGNORECASE)
    n = re.sub(r",?\s+in\s+her\s+official\s+capacity.*$", "", n, flags=re.IGNORECASE)
    n = re.sub(r",?\s+as\s+[^,]+$", "", n, flags=re.IGNORECASE)
    n = re.sub(r",?\s+Wife\s+of\s+.*$", "", n, flags=re.IGNORECASE)
    n = re.sub(r",?\s+on\s+(?:his|her|their)\s+own\s+behalf.*$", "", n, flags=re.IGNORECASE)
    return n.strip(" ,")


def clean_caption_party_name(name: str) -> str:
    """Remove only capacity clauses while preserving caption spelling/case."""
    n = (name or "").strip(" ,")
    n = re.sub(r",?\s+individually.*$", "", n, flags=re.IGNORECASE)
    n = re.sub(r",?\s+in\s+(?:his|her|their)\s+official\s+capacity.*$", "", n, flags=re.IGNORECASE)
    n = re.sub(r",?\s+as\s+[^,]+$", "", n, flags=re.IGNORECASE)
    n = re.sub(r",?\s+Wife\s+of\s+.*$", "", n, flags=re.IGNORECASE)
    return n.strip(" ,")


def normalize_state_2(state: str) -> str:
    s = normalize_caps(state)
    return s[:2].upper() if len(s) >= 2 else s.upper()


def normalize_firm_base(firm: str) -> str:
    raw = (firm or "").strip()
    raw = re.sub(r"\s*-\s*[A-Za-z]{2,20}\s*$", "", raw)
    raw = re.sub(r"\s*\([A-Za-z]{2,20}\)\s*$", "", raw)
    f = normalize_name_for_match(raw)
    f = re.sub(r"\s+(?:us|usa|united states)$", "", f)
    f = re.sub(r"\b(llp|pllc|pc|pa|llc|ltd|us|usa)\b", " ", f)
    return re.sub(r"\s+", " ", f).strip()


def firms_related(base_a: str, base_b: str) -> bool:
    if not base_a or not base_b:
        return False
    if base_a == base_b:
        return True
    return base_a in base_b or base_b in base_a


def pluralize_title(status: str) -> str:
    """Pluralize attorney titles per .txt Part IV."""
    if not status:
        return status
    if status.lower() == "pro hac vice":
        return status
    if status.lower() not in {
        "attorney general", "attorneys general", "district attorney",
        "public defender", "federal public defender", "assistant attorney general",
        "government attorney", "ausA".lower(), "u.s. attorney",
        "united states attorney",
    }:
        return status
    if status.endswith("s"):
        return status
    if status.upper() == "AUSA":
        return "AUSAs"
    if status.endswith("y"):
        return status[:-1] + "ies"
    return status + "s"


def build_representation_suffix(designation: str, party_names: List[str], no_designation: bool = False) -> str:
    """Build 'for Party' suffix per .txt Part III."""
    if no_designation:
        target = ", ".join([clean_party_name_for_output(pn) for pn in party_names if pn])
        return f"for {target}." if target else ""

    pname = ", ".join([clean_party_name_for_output(pn) for pn in party_names if pn])
    if pname:
        designation = pluralize_designation(designation, len([p for p in party_names if p]))
        return f"for {designation} {pname}."
    return f"for {designation}."


def display_party_names(parties: List[Party], caption: Optional[dict]) -> List[str]:
    """Use caption spelling for explicit parties; participant names for et al."""
    if not caption:
        return [p.name for p in parties]
    if caption.get("no_designation"):
        return [clean_party_name_for_output(p.name) for p in parties]
    caption_names = caption.get("output_names", caption.get("names", []))
    result = []
    for party in parties:
        if caption.get("no_designation"):
            match = next((name for name in caption_names
                          if names_equivalent(name, party.name)), None)
            if match:
                result.append(clean_caption_party_name(match))
                continue
        match = next((name for name in caption_names
                      if names_equivalent(name, party.name)), None)
        result.append(clean_caption_party_name(match or party.name))
    return result


def visible_status(status: str) -> str:
    """Hide only the explicit No Notice status from final attorney lines."""
    if status.strip().lower() == "no notice":
        return ""
    return status


def format_attorney_lines(attorneys: List[Attorney], designation: str,
                          party_names: List[str], no_designation: bool = False,
                          jurisdiction: str = 'federal') -> List[str]:
    """Format one representation as one line with internal firm groups."""
    suffix = build_representation_suffix(designation, party_names, no_designation=no_designation)
    groups: List[List[Attorney]] = []
    for attorney in attorneys:
        base = normalize_firm_base(attorney.firm)
        city = normalize_caps(attorney.city)
        state = normalize_state_2(attorney.state)
        target = next((group for group in groups
                       if normalize_firm_base(group[0].firm)
                       and firms_related(base, normalize_firm_base(group[0].firm))
                       and city == normalize_caps(group[0].city)
                       and state == normalize_state_2(group[0].state)), None)
        if target is None:
            groups.append([attorney])
        else:
            target.append(attorney)

    segments: List[str] = []
    for group in groups:
        first = max(group, key=lambda attorney: len(attorney.firm or ""))
        city = normalize_caps(first.city)
        state = normalize_state_2(first.state) if jurisdiction == 'federal' else ''
        if all(a.is_pro_se for a in group):
            parts = []
            for attorney in group:
                org = attorney.firm if attorney.firm and "correctional" not in attorney.firm.lower() else ""
                parts.append(", ".join(x for x in (attorney.name, org) if x))
            left = ", ".join(x for x in (", ".join(parts), city, state, "Pro Se") if x)
        else:
            same_status = len({a.status.lower() for a in group}) == 1
            names = ", ".join(a.name for a in group if a.name)
            repeat_status = any(a.status.lower() == "pro hac vice" for a in group)
            if repeat_status:
                entries = ", ".join(
                    ", ".join(x for x in (a.name, visible_status(a.status)) if x)
                    for a in group
                )
                address = ", ".join(x for x in (first.firm, city, state) if x)
                left = ", ".join(x for x in (entries, address) if x)
            elif same_status:
                status = pluralize_title(first.status) if len(group) > 1 else first.status
                address = ", ".join(x for x in (first.firm, city, state) if x)
                left = ", ".join(x for x in (names, visible_status(status), address) if x)
            else:
                entries = ", ".join(
                    ", ".join(x for x in (a.name, visible_status(a.status)) if x)
                    for a in group
                )
                address = ", ".join(x for x in (first.firm, city, state) if x)
                left = ", ".join(x for x in (entries, address) if x)
        segments.append(left)
    if not segments:
        return []
    if all(a.is_pro_se for a in attorneys):
        return [f"{', '.join(segments)}."]
    return [f"{', '.join(segments)}, {suffix}" if suffix
            else f"{', '.join(segments)}."]


def build_output_lines(title_info: Dict[str, dict], selected_parties: List[Party],
                       jurisdiction: str = 'federal') -> List[str]:
    """Build output lines per .txt Part III: group by representation."""
    parties_by_type: Dict[str, List[Party]] = defaultdict(list)
    for p in selected_parties:
        parties_by_type[normalize_name_for_match(p.party_type)].append(p)

    lines: List[str] = []

    for ptype_key, parties in parties_by_type.items():
        caption = None
        for _, v in title_info.items():
            if normalize_name_for_match(v["designation"]) == ptype_key:
                caption = v
                break

        if caption is None and "__no_designation__" in title_info:
            caption = title_info["__no_designation__"]

        if "amic" in ptype_key:
            designation = "Amicus" if len(parties) == 1 else "Amici"
            caption = {"designation": designation, "names": [], "has_et_al": True}

        no_designation = caption is None or bool((caption or {}).get("no_designation"))
        designation = (caption or {}).get("designation", normalize_caps(parties[0].party_type) or "Party")

        all_sets = [party_attorney_set_signature(p) for p in parties]
        identical = len(set(all_sets)) == 1

        # Skip parties with no attorneys
        non_empty_parties = [p for p in parties if len(party_attorney_set_signature(p)) > 0]
        if not non_empty_parties:
            continue

        if identical:
            # IDENTICAL representation: all parties have same attorneys
            rep_attorneys = non_empty_parties[0].attorneys

            include_names = False
            caption_names = (caption or {}).get("names", [])
            if "amic" in ptype_key:
                include_names = True
            if no_designation:
                include_names = True
            if len(caption_names) >= 2 and len(parties) != len(caption_names):
                include_names = True

            if caption_names:
                found_any_caption_name = any(
                    any(names_equivalent(cn, p.name) for p in parties) for cn in caption_names
                )
                if not found_any_caption_name:
                    include_names = True

            if include_names:
                new_lines = format_attorney_lines(
                    rep_attorneys, designation,
                    display_party_names(parties, caption),
                    no_designation=no_designation,
                    jurisdiction=jurisdiction,
                )
            else:
                new_lines = format_attorney_lines(
                    rep_attorneys, designation, [],
                    no_designation=no_designation,
                    jurisdiction=jurisdiction,
                )
            lines.extend(new_lines)
            continue

        # DIFFERENT representation: group by unique attorney set
        groups: Dict[Tuple[Tuple[str, str, str, str, str], ...], List[Party]] = defaultdict(list)
        for p in non_empty_parties:
            groups[party_attorney_set_signature(p)].append(p)

        for _, ps in groups.items():
            attorneys = ps[0].attorneys
            lines.extend(format_attorney_lines(
                attorneys, designation,
                display_party_names(ps, caption),
                no_designation=no_designation,
                jurisdiction=jurisdiction,
            ))

    return lines


def format_attorney_blocks(lines: List[str]) -> str:
    """Wrap all attorney lines in one content attorney block."""
    if not lines:
        return ""
    rendered = "\n".join(
        f'<attorney.line first-line="1">{escape(line, quote=False)}</attorney.line>'
        for line in lines
    )
    return (
        '<content.attorney.block>\n'
        '<content.attorney>\n'
        f'{rendered}\n'
        '</content.attorney>\n'
        '</content.attorney.block>'
    )


def process_xml_to_json(xml_content: bytes) -> Dict[str, dict]:
    root = ET.fromstring(_strip_leading_junk(xml_content))
    jurisdiction = infer_jurisdiction(root)
    title_text = extract_title_text(root)
    title_info = parse_title_parties(title_text)
    all_parties = parse_parties(root)
    selected_parties = pick_parties_for_output(all_parties, title_info)
    lines = build_output_lines(title_info, selected_parties, jurisdiction)

    return {"response": {"content.attorney": lines}}


def _strip_leading_junk(xml_content: bytes) -> bytes:
    """Drop any bytes before the first '<' (e.g. browser 'Save Page As' preamble text)."""
    idx = xml_content.find(b"<")
    return xml_content[idx:] if idx > 0 else xml_content


def process_xml_to_attorney_blocks(xml_content: bytes) -> str:
    """Main entry point: XML → attorney blocks per user's per-attorney block format."""
    root = ET.fromstring(_strip_leading_junk(xml_content))
    jurisdiction = infer_jurisdiction(root)
    title_text = extract_title_text(root)
    title_info = parse_title_parties(title_text)
    all_parties = parse_parties(root)
    selected_parties = pick_parties_for_output(all_parties, title_info)
    lines = build_output_lines(title_info, selected_parties, jurisdiction)
    return format_attorney_blocks(lines)


def fetch_data_by_document_uuid(guid_uuid: str):
    url = f"http://dataprocessingtools.int.thomsonreuters.com/pgs_Tools_Novus/GetNovusDocsByGuid.aspx?uid={guid_uuid}&env=P"
    st.write(f"Constructed URL: {url}")
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            st.success("Successfully fetched data.")
            return response.content
        st.error(f"Failed to fetch data. Status Code: {response.status_code}")
        return None
    except requests.exceptions.RequestException as e:
        st.error(f"An error occurred: {str(e)}")
        return None


def main():
    st.title("Attorney Information Extractor")

    st.caption(
        "Note: fetching by GUID requires access to TR's internal network. "
        "If that fails (e.g. on Streamlit Cloud), upload the XML file instead."
    )
    uploaded_file = st.file_uploader("Or upload a Novus XML file", type=["xml"])
    guid_uuid = st.text_input("Enter Guid uuid:")

    fetched_data = None
    if st.button("Fetch and Extract Information"):
        if uploaded_file is not None:
            fetched_data = uploaded_file.read()
        elif guid_uuid:
            fetched_data = fetch_data_by_document_uuid(guid_uuid)
        else:
            st.warning("Please enter a valid Guid uuid or upload an XML file.")
            return

        if not fetched_data:
            return

        try:
            payload = process_xml_to_attorney_blocks(fetched_data)
            st.text(payload)
        except ET.ParseError as e:
            st.error(f"XML parsing failed: {e}")
        except Exception as e:
            st.error(f"Processing failed: {e}")


if __name__ == "__main__":
    main()
