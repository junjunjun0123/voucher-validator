"""
Connect cinema ID -> full cinema name.

Pulled from  GET /OData.svc/Cinemas  on the Vista Connect host.
The IDs are short alphabetic codes used by TGV (e.g. "PKL", "BU0", "1AV").

The schedule page (172.31.22.65/screenschedule) shows *display names*
("Pavilion KL"), while the Connect API needs the *ID* ("PKL"), so we
translate between the two in `resolve_cinema_id()` inside app.py.
"""

CINEMA_MAP = {
    "1AV": "TGV 1st Avenue",
    "1SM": "TGV 1 Shamelin",
    "ALM": "TGV Alamanda",
    "AMP": "TGV Ampang Point",
    "AU2": "TGV AU2",
    "BBT": "TGV Bukit Tinggi",
    "BI0": "TGV Bukit Indah",
    "BIN": "BINTULU PANTIASA",
    "BKM": "TGV Bukit Mertajam",
    "BR0": "TGV Bukit Raja",
    "BU0": "TGV 1 Utama",
    "CHR": "TGV Cheras Selatan",
    "CTR": "TGV Cheras Sentral",
    "CYB": "TGV DPulze",
    "GUR": "TGV Gurney Paragon",
    "ICT": "TGV Central I - City",
    "IMP": "TGV Miri",
    "IP0": "TGV Kinta City",
    "JAY": "TGV Jaya",
    "KLC": "TGV Suria KLCC",
    "KLE": "TGV Klebang",
    "KP0": "TGV Kepong",
    "KSL": "TGV KSL",
    "KUL": "TGV Kulaijaya",
    "MAN": "TGV Seri Manjung",
    "MN0": "TGV Mines",
    "MSR": "TGV Mesra Mall",
    "PBJ": "TGV Pavilion Bukit Jalil",
    "PDH": "TGV Pavilion Damansara Heights",
    "PKL": "TGV Pavilion Kuala Lumpur",
    "RWK": "TGV Rawang",
    "S18": "TGV Station 18",
    "S20": "TGV Seremban 2",
    "STR": "TGV Encorp Strand",
    "STW": "TGV SetiaWalk",
    "SW0": "TGV Sunway Pyramid",
    "SWP": "TGV Sunway Putra",
    "SWS": "TGV Sunway Square",
    "SWV": "TGV Sunway Velocity",
    "TAI": "TGV Taiping",
    "TBR": "TGV Tebrau City",
    "TOP": "TGV TOPPEN",
    "TSC": "TASEK CENTRAL",
    "VIV": "TGV Vivacity Megamall",
    "WWM": "TGV Wangsa Walk",
}
