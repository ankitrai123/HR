"""Regenerate data/question_bank.json from the frontend question file plus the
provisional item key below.

The key assigns each item to one of the 11 competency dimensions and marks
reverse-keyed items ("R"). It is a PROVISIONAL content-based key written for
this project, NOT the publisher's scoring key; replace it with a validated key
before using scores for hiring decisions.

Run:  python data/build_question_bank.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRONTEND_TEST = HERE.parents[1] / "src" / "data" / "test.json"

DIMENSIONS = {
    "EP": ("Ethical Propensity", "Personal"),
    "IT": ("Initiative Taking", "Personal"),
    "AD": ("Adaptability", "Personal"),
    "TW": ("Team Work", "Interpersonal"),
    "NW": ("Networking", "Interpersonal"),
    "NI": ("Negotiation & Influence", "Interpersonal"),
    "SO": ("Service Orientation", "Excellence"),
    "RO": ("Result Orientation", "Excellence"),
    "LE": ("Leading by Example", "Leadership"),
    "IN": ("Innovation", "Leadership"),
    "SS": ("Strategic Orientation", "Leadership"),
}

# item id -> dimension code, with an "R" suffix for reverse-keyed items.
KEY = {
    1: "SS R", 2: "EP", 3: "EP R", 4: "EP", 5: "NW", 6: "NW", 7: "AD", 8: "IN R",
    9: "NI R", 10: "AD R", 11: "SS", 12: "SS R", 13: "TW R", 14: "SO R", 15: "IT",
    16: "IN", 17: "NI", 18: "RO", 19: "EP", 20: "EP", 21: "EP", 22: "NI R",
    23: "AD R", 24: "TW R", 25: "AD", 26: "LE", 27: "TW", 28: "RO", 29: "AD",
    30: "NW", 31: "AD R", 32: "IT R", 33: "SO R", 34: "LE R", 35: "EP R",
    36: "IN R", 37: "NI", 38: "NW", 39: "NI R", 40: "IT R", 41: "LE R",
    42: "AD R", 43: "RO", 44: "RO R", 45: "SS", 46: "RO R", 47: "IT", 48: "AD R",
    49: "IN", 50: "TW", 51: "EP R", 52: "SS", 53: "SS", 54: "SO", 55: "RO",
    56: "TW", 57: "TW R", 58: "TW R", 59: "SS", 60: "SO", 61: "SO", 62: "IN",
    63: "IN", 64: "NI", 65: "TW", 66: "TW", 67: "LE", 68: "SS", 69: "RO",
    70: "RO", 71: "RO", 72: "RO", 73: "AD R", 74: "IT R", 75: "AD R",
    76: "RO R", 77: "IT R", 78: "RO", 79: "RO R", 80: "AD R", 81: "AD R",
    82: "IN R", 83: "LE", 84: "LE", 85: "SS R", 86: "AD R", 87: "LE R",
    88: "AD", 89: "NI R", 90: "AD R", 91: "LE R", 92: "LE R", 93: "LE",
    94: "NI", 95: "NI", 96: "NI", 97: "NI", 98: "NW", 99: "NW R", 100: "NW R",
    101: "NW R", 102: "NW", 103: "NW", 104: "NW", 105: "TW", 106: "TW",
    107: "TW R", 108: "AD R", 109: "SO", 110: "NI", 111: "SO", 112: "LE",
    113: "IT", 114: "IN", 115: "NW", 116: "EP", 117: "NW R", 118: "SO",
    119: "IT", 120: "IT", 121: "AD", 122: "IN", 123: "IN", 124: "RO",
    125: "IN R", 126: "IN", 127: "IN", 128: "IN", 129: "AD", 130: "AD",
    131: "IN R", 132: "IT", 133: "SO", 134: "SO", 135: "SO", 136: "RO R",
    137: "RO", 138: "RO", 139: "RO", 140: "AD R", 141: "AD", 142: "AD",
    143: "LE", 144: "LE", 145: "LE", 146: "LE", 147: "LE", 148: "NI",
    149: "IT", 150: "IT", 151: "IT R", 152: "LE", 153: "IT", 154: "SS",
    155: "SS", 156: "IN", 157: "SS", 158: "SS", 159: "SS", 160: "SS R",
    161: "SS R", 162: "SS R", 163: "SS", 164: "SS R", 165: "SS", 166: "SS",
    167: "RO", 168: "RO", 169: "SO", 170: "SO R", 171: "LE", 172: "LE",
    173: "EP", 174: "LE", 175: "EP",
}


def main() -> None:
    test = json.loads(FRONTEND_TEST.read_text(encoding="utf-8"))
    questions = [q for s in test["sections"] for q in s["questions"]]
    assert sorted(KEY) == [q["id"] for q in questions], "key must cover every item exactly once"

    items = []
    for q in questions:
        code, _, rev = KEY[q["id"]].partition(" ")
        items.append({
            "id": q["id"],
            "text": q["questionText"],
            "dimension": DIMENSIONS[code][0],
            "reverse_keyed": rev == "R",
        })

    bank = {
        "instrument": "Personality Map (paraphrased)",
        "key_status": "provisional",
        "dimensions": [{"name": n, "category": c} for n, c in DIMENSIONS.values()],
        "items": items,
    }
    out = HERE / "question_bank.json"
    out.write_text(json.dumps(bank, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    counts = {}
    for it in items:
        counts.setdefault(it["dimension"], [0, 0])
        counts[it["dimension"]][0] += 1
        counts[it["dimension"]][1] += it["reverse_keyed"]
    for dim, (n, r) in counts.items():
        print(f"{dim:26s} items={n:3d} reverse={r}")
    print(f"wrote {out.relative_to(HERE.parent)} ({len(items)} items)")


if __name__ == "__main__":
    main()
