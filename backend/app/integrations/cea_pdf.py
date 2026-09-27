"""Parser for the CEA "List of Thermal/Hydro/Nuclear Power Stations" PDF (e.g. as on 31.03.2025).

The PDF lists generating units, one per row: region, state, sector, organisation, name of project, prime mover, unit
number, installed capacity (MW) and year of commissioning, with per-state and per-region "Total" rows. Appendix A lists
thermal stations, B hydro, C nuclear. **It contains no coordinates or districts**; locations must come from elsewhere.

Text is taken in pypdf's layout mode (columns separated by runs of spaces). Known irregularities are repaired
deterministically and every repair is recorded; rows that cannot be parsed are returned, never dropped silently.
The printed state totals are used to check that no unit was lost or double counted.
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REGIONS = "NR|WR|SR|ER|NER"
MOVERS = ("GT-Gas", "GT-Liquid", "GT-Naphtha", "Steam", "Diesel", "Nuclear", "Hydro")
CATEGORY = {"A": "thermal", "B": "hydro", "C": "nuclear"}

_ROW = re.compile(rf"^\s*(?P<sno>\d+)?\s+(?P<region>{REGIONS})\s+(?P<state>.+?)\s*(?P<sector>Central|State|Private)\s+Sector\s*(?P<rest>.*)$")
_TAIL = re.compile(rf"^(?P<left>.*?)\s*(?P<mover>{'|'.join(re.escape(m) for m in MOVERS)})\s+(?P<unit>\S+)\s+"
                   r"(?P<cap>\d+(?:\.\d+)?)(?:\s+(?P<year>\d{4}))?\s*$")
_STATE_TOTAL = re.compile(rf"^\s*(?P<region>{REGIONS})\s+(?P<state>.+?)\s+Total\s+(?P<cap>\d+(?:\.\d+)?)\s*$")
_REGION_TOTAL = re.compile(rf"^\s*(?P<region>{REGIONS})\s+Total\s+(?P<cap>\d+(?:\.\d+)?)\s*$")
_APPENDIX = re.compile(r"Appendix-([A-Z])")
_CATEGORY_TOTAL = re.compile(r"^\s*(?P<cat>Thermal|Hydro|Nuclear)\s+Total\s+(?P<cap>\d+(?:\.\d+)?)\s*$")


@dataclass
class CEAUnit:
    appendix: str
    region: str
    state: str
    sector: str
    organisation: str
    project: str
    prime_mover: str
    unit: str
    capacity_mw: float
    year: int | None
    page: int
    serial: int | None
    repairs: list[str] = field(default_factory=list)


@dataclass
class ParsedCEA:
    units: list[CEAUnit]
    unparsed: list[tuple[int, str]]
    state_totals: dict[tuple[str, str, str], float]  # (appendix, region, state) -> printed total MW
    region_totals: dict[tuple[str, str], float]
    category_totals: dict[str, float] = field(default_factory=dict)  # "thermal" | "hydro" | "nuclear" -> printed MW


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_lines(pages: list[str]) -> ParsedCEA:
    units: list[CEAUnit] = []
    unparsed: list[tuple[int, str]] = []
    state_totals: dict[tuple[str, str, str], float] = {}
    region_totals: dict[tuple[str, str], float] = {}
    category_totals: dict[str, float] = {}
    appendix = "A"
    for page_no, text in enumerate(pages, start=1):
        m = _APPENDIX.search(text[:600])
        if m:
            appendix = m.group(1)
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line.strip():
                continue
            if (t := _CATEGORY_TOTAL.match(line)):
                category_totals[t["cat"].lower()] = float(t["cap"])
                continue
            if (t := _REGION_TOTAL.match(line)):
                region_totals[(appendix, t["region"])] = float(t["cap"])
                continue
            if (t := _STATE_TOTAL.match(line)):
                state_totals[(appendix, t["region"], _clean(t["state"]))] = float(t["cap"])
                continue
            m = _ROW.match(line)
            if not m:
                if not re.search(r"S\.No|Appendix|List\s+of|Capacity\(MW\)|Grand\s+Total|^\s*Total", line):
                    unparsed.append((page_no, _clean(line)))
                continue
            rest = m["rest"].strip()
            tail = _TAIL.match(rest)
            if not tail:
                unparsed.append((page_no, _clean(line)))
                continue
            repairs = []
            left = tail["left"].strip()
            if tail.start("mover") > 0 and not rest[tail.start("mover") - 1].isspace():
                repairs.append("prime_mover_separated")  # glued to the project name ("...PROJECTGT-Gas")
            parts = [p for p in re.split(r"\s{2,}", left) if p]
            if len(parts) >= 2:
                org, project = parts[0], " ".join(parts[1:])
            elif len(parts) == 1:
                half = len(parts[0]) // 2
                if len(parts[0]) % 2 == 0 and parts[0][:half] == parts[0][half:]:
                    org = project = parts[0][:half]  # organisation printed twice without a separator (OPG)
                    repairs.append("organisation_repeated")
                else:
                    org, project = parts[0], parts[0]
                    repairs.append("organisation_project_merged")
            else:
                unparsed.append((page_no, _clean(line)))
                continue
            units.append(CEAUnit(
                appendix=appendix, region=m["region"], state=_clean(m["state"]), sector=f"{m['sector']} Sector",
                organisation=_clean(org), project=_clean(project), prime_mover=tail["mover"], unit=tail["unit"],
                capacity_mw=float(tail["cap"]), year=int(tail["year"]) if tail["year"] else None, page=page_no,
                serial=int(m["sno"]) if m["sno"] else None, repairs=repairs))
    return ParsedCEA(units, unparsed, state_totals, region_totals, category_totals)


def parse_pdf(path: Path) -> ParsedCEA:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return parse_lines([p.extract_text(extraction_mode="layout") or "" for p in reader.pages])


def reconcile(parsed: ParsedCEA) -> list[dict]:
    """Compare parsed unit capacity with the PDF's printed state totals. Returns one row per printed total."""
    sums: dict[tuple[str, str, str], float] = defaultdict(float)
    for u in parsed.units:
        sums[(u.appendix, u.region, u.state)] += u.capacity_mw
    out = []
    for key, printed in sorted(parsed.state_totals.items()):
        got = round(sums.get(key, 0.0), 3)
        out.append({"appendix": key[0], "region": key[1], "state": key[2], "printed_mw": printed, "parsed_mw": got,
                    "ok": abs(got - printed) <= max(0.05, printed * 1e-4)})
    return out
