"""Africa's Talking USSD flow (stateless: the full answer path arrives in `text`, joined by '*').

Screens (each <= ~160 characters because USSD screens are small):
  ''            -> choose language
  '1' / '2'     -> choose market
  '..*m'        -> choose animal condition
  '..*m*c'      -> enter number of animals
  '..*m*c*n'    -> END with advice
Only English and Afaan Oromoo are offered on the phone: Amharic (Ge'ez) script often does not display
over USSD on cheaper handsets/gateways. Test it on real handsets before adding it.
"""
import os
from data_store import GRADES
from engine import advise, MAX_HERD
import texts

# Markets shown on the phone menu (edit to match your service area; names must match the CSV).
USSD_MARKETS = [m.strip() for m in os.environ.get(
    "USSD_MARKETS", "Nagelle Borana,Yabalo,Arero,Moyale Oromiya,Miyo").split(",")]
LANGS = {"1": "en", "2": "om"}
GRADE_KEYS = {"1": "Thin", "2": "Moderate Weight", "3": "Very Fat"}

UI = {
    "en": {"market": "Select market:", "grade": "Animal condition:\n1. Thin\n2. Medium\n3. Fat", "count": "How many animals? (type a number)",
           "bad": "Wrong choice.\n", "price": "Price", "birr": "Birr each", "conf": "Confidence", "tip": "Sell the thinnest first.",
           "offline": "Forecast offline", "normal": "Normal rains", "drought": "Moderate drought"},
    "om": {"market": "Gabaa filadhu:", "grade": "Haala loonii:\n1. Dadhabaa\n2. Giddu galeessa\n3. Furdaa", "count": "Loon meeqa qabda? (lakkoofsa barreessi)",
           "bad": "Filannoon dogoggora.\n", "price": "Gatii", "birr": "Birr tokkoon", "conf": "Amanamummaa", "tip": "Dadhaboo duraan gurguri.",
           "offline": "Tilmaamni hin jiru", "normal": "Rooba idilee", "drought": "Hongee giddu galeessa"},
}


def _menu(items):
    return "\n".join("%d. %s" % (i + 1, m) for i, m in enumerate(items))


def handle(text):
    parts = [p.strip() for p in (text or "").split("*")] if text else []
    if not parts:
        return "CON Livestock advice / Gorsa Loonii\n1. English\n2. Afaan Oromoo"
    lang = LANGS.get(parts[0])
    if not lang:
        return "CON Wrong choice / Dogoggora\n1. English\n2. Afaan Oromoo"
    u = UI[lang]
    if len(parts) == 1:
        return "CON %s\n%s" % (u["market"], _menu(USSD_MARKETS))
    try:
        market = USSD_MARKETS[int(parts[1]) - 1]
        if int(parts[1]) < 1:
            raise IndexError
    except (ValueError, IndexError):
        return "CON %s%s\n%s" % (u["bad"], u["market"], _menu(USSD_MARKETS))
    if len(parts) == 2:
        return "CON %s" % u["grade"]
    grade = GRADE_KEYS.get(parts[2])
    if not grade:
        return "CON %s%s" % (u["bad"], u["grade"])
    if len(parts) == 3:
        return "CON %s" % u["count"]
    if not parts[3].isdigit() or not (0 < int(parts[3]) <= MAX_HERD):
        return "CON %s%s" % (u["bad"], u["count"])
    herd = int(parts[3])
    try:
        a = advise(market, grade, herd, lang)
    except Exception:
        return "END Service busy, try again later.\nSirni hin hojjenne, booda yaali."
    conf = texts.CONF[a["confidence"]][lang]
    price = f"{a['price_now_per_animal']:,}"
    if a["status"] == "unavailable":
        # never present 'no forecast' as 'no drought': show the advice for normal rains AND for a moderate drought
        sc = {s["severity"]: s["action"] for s in a["scenarios"]}
        return "END %s\n%s: %s\n%s: %s\n%s: ~%s %s" % (
            u["offline"], u["normal"], texts.SHORT_ACTION[sc[0]][lang], u["drought"], texts.SHORT_ACTION[sc[2]][lang],
            u["price"], price, u["birr"])
    msg = "END %s\n%s: ~%s %s\n%s: %s" % (texts.SHORT_ACTION[a["action"]][lang], u["price"], price, u["birr"], u["conf"], conf)
    if a["action"] != "hold":
        msg += "\n" + u["tip"]
    return msg
