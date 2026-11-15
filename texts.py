"""All user-facing words, in English (en), Afaan Oromoo (om) and Amharic (am).
NOTE: om/am wording was drafted quickly and MUST be reviewed by a native speaker before real use."""

ACTION_TITLE = {
    "hold":    {"en": "HOLD - do not sell yet",       "om": "AMMAAF QABADHU - hin gurguramin", "am": "ለአሁን ያቆዩ - አይሽጡ"},
    "sell_25": {"en": "SELL 25% now",                 "om": "AMMA %25 GURGURI",               "am": "አሁን 25% ይሽጡ"},
    "sell_50": {"en": "SELL 50% now",                 "om": "AMMA %50 GURGURI",               "am": "አሁን 50% ይሽጡ"},
    "sell_75": {"en": "SELL 75% now",                 "om": "AMMA %75 GURGURI",               "am": "አሁን 75% ይሽጡ"},
}
SHORT_ACTION = {
    "hold":    {"en": "HOLD for now", "om": "Ammaaf qabadhu"},
    "sell_25": {"en": "SELL 25% now", "om": "Amma %25 gurguri"},
    "sell_50": {"en": "SELL 50% now", "om": "Amma %50 gurguri"},
    "sell_75": {"en": "SELL 75% now", "om": "Amma %75 gurguri"},
}
CONF = {
    "high":   {"en": "High",   "om": "Ol'aanaa",     "am": "ከፍተኛ"},
    "medium": {"en": "Medium", "om": "Giddu galeessa", "am": "መካከለኛ"},
    "low":    {"en": "Low",    "om": "Gadi aanaa",   "am": "ዝቅተኛ"},
}
GRADE_NAME = {
    "Thin":            {"en": "thin",   "om": "dadhabaa",       "am": "ከሲታ"},
    "Moderate Weight": {"en": "medium", "om": "giddu galeessa", "am": "መካከለኛ"},
    "Very Fat":        {"en": "fat",    "om": "furdaa",         "am": "ወፍራም"},
}
REASON = {
    "price": {
        "en": "Price now at {market}: about {price:,} Birr per {grade} animal.",
        "om": "Gatiin amma {market}: bira {price:,} Birr loon {grade} tokkoof.",
        "am": "አሁን በ{market} ዋጋ: ለአንድ {grade} እንስሳ ከ{price:,} ብር ገደማ።"},
    "drought_high": {
        "en": "Drought risk is high: animals may get thinner or die, and prices may fall.",
        "om": "Balaan hongeetii ol'aanaadha: loon dadhabuu ykn du'uu danda'a, gatiin xiqqaachuu danda'a.",
        "am": "የድርቅ ስጋት ከፍተኛ ነው፤ እንስሳት ሊከሱ ወይም ሊሞቱ፣ ዋጋም ሊወርድ ይችላል።"},
    "drought_low": {
        "en": "Drought risk looks low for the next 3 months.",
        "om": "Balaan hongeetii ji'oota 3 itti aanuuf xiqqaadha.",
        "am": "ለሚቀጥሉት 3 ወራት የድርቅ ስጋት ዝቅተኛ ነው።"},
    "drought_mid": {
        "en": "Some drought risk in the next 3 months.",
        "om": "Ji'oota 3 itti aanuu keessatti balaan hongeetii muraasni jira.",
        "am": "በሚቀጥሉት 3 ወራት የተወሰነ የድርቅ ስጋት አለ።"},
    "hold_better": {
        "en": "Waiting is expected to pay about {pct:.1f}% more than selling today.",
        "om": "Eeggachuun gurguruu har'aa caalaa %{pct:.1f} ol argamsiisa jedhamee eegama.",
        "am": "መጠበቅ ዛሬ ከመሸጥ በ{pct:.1f}% የበለጠ ይከፍላል ተብሎ ይጠበቃል።"},
    "sell_better": {
        "en": "Waiting is expected to pay about {pct:.1f}% LESS than selling today.",
        "om": "Eeggachuun gurguruu har'aa caalaa %{pct:.1f} xiqqaa argamsiisa jedhamee eegama.",
        "am": "መጠበቅ ዛሬ ከመሸጥ በ{pct:.1f}% ያነሰ ይከፍላል ተብሎ ይጠበቃል።"},
    "pressure_high": {
        "en": "Prices are falling across many markets - a sign many people are selling. If everyone sells late, prices can crash.",
        "om": "Gatiin gabaawwan baay'ee keessatti gadi bu'aa jira - namoonni baay'een gurgurachaa jiru jechuudha. Yoo hunduu booda gurgure gatiin gadi bu'uu danda'a.",
        "am": "በብዙ ገበያዎች ዋጋ እየወረደ ነው - ብዙ ሰዎች እየሸጡ ነው ማለት ነው። ሁሉም ዘግይቶ ከሸጠ ዋጋ ሊወድቅ ይችላል።"},
    "regional_outlook": {
        "en": "The drought forecast covers the whole {region} region, so it is less exact for this town.",
        "om": "Tilmaamni hongee naannoo {region} guutuu kan ilaallu waan ta'eef magaalaa kanaaf sirrii hin ta'u.",
        "am": "የድርቅ ትንበያው መላውን የ{region} ክልል የሚሸፍን ስለሆነ ለዚህ ከተማ ትክክለኛነቱ ያነሰ ነው።"},
    "thin_first": {
        "en": "Sell the thinnest animals first - they lose the most value and die first.",
        "om": "Loon dadhaboo duraan gurguri - isaan gatii baay'ee dhaban, duraan du'u.",
        "am": "መጀመሪያ በጣም የከሱትን ይሽጡ - ብዙ ዋጋ ያጣሉ፣ መጀመሪያም ይሞታሉ።"},
    "best_month": {
        "en": "If condition stays the same, the best time to sell is in about {m} month(s).",
        "om": "Yoo haalli loonii hin jijjiiramne, yeroo gurguruuf filatamaan woggaa ji'a {m} ta'a.",
        "am": "የእንስሳው ሁኔታ ካልተቀየረ፣ ለመሸጥ ምርጡ ጊዜ በ{m} ወር ውስጥ ነው።"},
    "low_data": {
        "en": "Little recent price data for this market - treat this advice with care.",
        "om": "Daataan gatii dhiyoo gabaa kanaaf xiqqaadha - gorsa kana of eeggannoodhaan fayyadami.",
        "am": "ለዚህ ገበያ የቅርብ ጊዜ የዋጋ መረጃ ጥቂት ነው - ምክሩን በጥንቃቄ ይጠቀሙ።"},
    "no_drought_model": {
        "en": "Drought forecast is not connected yet - assuming normal conditions.",
        "om": "Tilmaamni hongee ammaaf hin walqabsiifamne - haala idilee akka ta'e fudhatameera.",
        "am": "የድርቅ ትንበያ ገና አልተገናኘም - መደበኛ ሁኔታ እንደሆነ ተወስዷል።"},
}

SEV_NAME = {
    "en": ["No drought", "Mild drought", "Moderate drought", "Severe drought"],
    "om": ["Hongee hin jiru", "Hongee xiqqaa", "Hongee giddu galeessa", "Hongee cimaa"],
    "am": ["ድርቅ የለም", "ቀላል ድርቅ", "መካከለኛ ድርቅ", "ከባድ ድርቅ"],
}
IF_NORMAL = {"en": " (IF NORMAL CONDITIONS)", "om": " (YOO HAALLI IDILEEN JIRE)", "am": " (ሁኔታዎች መደበኛ ከሆኑ)"}
REASON.update({
    "data_basis": {
        "en": "Based on {n} price report(s) from the last {w} days; the newest is {d} day(s) old.",
        "om": "Gabaasa gatii {n} guyyoota {w} darban irratti hundaa'e; kan haaraan guyyaa {d} dura ture.",
        "am": "ባለፉት {w} ቀናት በ{n} የዋጋ ሪፖርት(ቶች) ላይ የተመሠረተ ነው፤ አዲሱ {d} ቀን ያስቆጠረ ነው።"},
    "drought_unavailable": {
        "en": "Drought forecast is unavailable or too old, so this headline advice assumes NORMAL conditions. See the scenario table.",
        "om": "Tilmaamni hongee hin argamu ykn baay'ee dulloomeera, kanaaf gorsi kun haala IDILEE akka ta'e fudhata. Gabatee haala ilaali.",
        "am": "የድርቅ ትንበያ የለም ወይም በጣም ያረጀ ነው፤ ስለዚህ ይህ ምክር ሁኔታዎች መደበኛ ናቸው ብሎ ይገምታል። የሁኔታዎችን ሰንጠረዥ ይመልከቱ።"},
    "drought_cached": {
        "en": "Using a saved drought forecast that is {age} day(s) old.",
        "om": "Tilmaama hongee olkaa'ame guyyaa {age} dulloomeera fayyadamaa jira.",
        "am": "{age} ቀን ያስቆጠረ የተቀመጠ የድርቅ ትንበያ በመጠቀም ላይ ነው።"},
    "scenario_mode": {
        "en": "You are viewing a SCENARIO ({name}), not a forecast.",
        "om": "HAALA fakkeeffame ({name}) ilaaltaa jirta, tilmaama miti.",
        "am": "የምትመለከቱት የተመሰለ ሁኔታ ({name}) ነው፣ ትንበያ አይደለም።"},
    "climatology_only": {
        "en": "The drought outlook is only the historical average for this time of year; it has no real skill about the coming months.",
        "om": "Tilmaamni hongee giddu galeessa seenaa yeroo kanaa qofa; ji'oota dhufan ilaalchisee dandeettii dhugaa hin qabu.",
        "am": "የድርቅ ትንበያው ለዚህ ጊዜ የታሪክ አማካይ ብቻ ነው፤ ስለሚመጡት ወራት እውነተኛ የመተንበይ ችሎታ የለውም።"},
    "fragile": {
        "en": "This advice changes a lot if the assumptions change slightly - treat it as a guide only.",
        "om": "Yoo yaadni xiqqoo jijjiiramu gorsi kun baay'ee jijjiirama - qajeelfama qofa godhi.",
        "am": "ግምቶች በጥቂቱ ቢቀየሩ ይህ ምክር በጣም ይቀየራል - እንደ መመሪያ ብቻ ይጠቀሙት።"},
})
