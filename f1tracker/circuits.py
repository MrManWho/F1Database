"""Country flags and simplified circuit outlines for the next-race card.

The outlines are original, deliberately simplified sketches (a rough impression of each layout on a
100 x 60 canvas), not official track maps. Rounds the tracker doesn't recognise get a generic loop.
"""

GENERIC = "M12 40 C12 18 30 12 50 12 C72 12 88 18 88 30 C88 44 70 48 50 48 C32 48 12 54 12 40 Z"

# keyword in the event name or location -> (country code, circuit name, outline path)
CIRCUITS = [
    (("australia", "melbourne", "albert park"), "AU", "Albert Park",
     "M14 34 L22 18 L40 12 L62 14 L80 10 L90 18 L84 30 L70 34 L74 46 L58 50 L36 48 L22 46 Z"),
    (("china", "chinese", "shanghai"), "CN", "Shanghai International Circuit",
     "M10 44 L30 44 L36 36 L28 28 L34 18 L48 16 L52 26 L62 28 L88 12 L90 22 L70 36 L66 46 L48 50 Z"),
    (("japan", "suzuka"), "JP", "Suzuka",
     "M10 30 C10 18 24 16 34 24 L50 38 C58 44 70 44 76 36 C82 28 90 30 90 38 C90 50 76 52 64 48 L40 32 C32 26 22 26 20 34 C18 42 10 42 10 30 Z"),
    (("bahrain", "sakhir"), "BH", "Bahrain International Circuit",
     "M16 46 L16 16 L40 12 L46 22 L66 20 L70 12 L88 16 L86 30 L68 32 L62 42 L80 46 L76 52 L30 52 Z"),
    (("saudi", "jeddah"), "SA", "Jeddah Corniche Circuit",
     "M12 48 L22 12 L28 10 L32 20 L40 14 L50 18 L58 12 L68 16 L78 12 L88 20 L84 30 L60 34 L46 44 L30 50 Z"),
    (("miami",), "US", "Miami International Autodrome",
     "M10 40 L10 22 L30 16 L60 16 L86 20 L90 30 L72 34 L68 42 L52 44 L46 36 L34 38 L28 46 Z"),
    (("canada", "canadian", "montreal", "villeneuve"), "CA", "Circuit Gilles Villeneuve",
     "M8 36 L14 28 L34 26 L52 18 L74 18 L92 26 L88 32 L70 32 L56 38 L34 40 L18 44 Z"),
    (("monaco", "monte carlo"), "MC", "Circuit de Monaco",
     "M10 42 L22 30 L30 34 L38 22 L52 18 L62 24 L74 16 L90 24 L82 36 L66 34 L58 42 L40 46 L26 48 Z"),
    (("barcelona", "catalunya", "spanish", "spain"), "ES", "Circuit de Barcelona-Catalunya",
     "M10 46 L10 22 L24 14 L50 14 L58 22 L74 18 L88 26 L84 36 L66 36 L60 44 L40 42 L28 48 Z"),
    (("austria", "austrian", "spielberg", "red bull ring"), "AT", "Red Bull Ring",
     "M12 44 L30 14 L42 14 L50 26 L88 22 L90 30 L64 38 L46 40 L34 48 Z"),
    (("brit", "silverstone"), "GB", "Silverstone",
     "M18 44 L10 30 L22 20 L34 22 L44 12 L62 14 L66 24 L82 22 L90 32 L78 42 L60 40 L50 48 L32 50 Z"),
    (("belgi", "spa"), "BE", "Spa-Francorchamps",
     "M10 18 L18 12 L26 22 L50 30 L78 22 L90 30 L84 44 L66 48 L52 42 L38 50 L22 44 L18 30 Z"),
    (("hungar", "budapest", "hungaroring"), "HU", "Hungaroring",
     "M16 14 L60 12 L86 18 L88 30 L72 32 L66 42 L46 40 L40 50 L20 48 L24 36 L12 28 Z"),
    (("dutch", "netherlands", "zandvoort"), "NL", "Zandvoort",
     "M14 40 C10 26 20 14 36 14 L60 16 C74 16 88 22 86 34 L72 36 L64 46 L44 44 L36 50 L22 48 Z"),
    (("italian", "italy", "monza"), "IT", "Monza",
     "M10 44 L10 20 L18 12 L60 12 L78 14 L90 24 L86 38 L72 44 L56 42 L50 48 L24 48 Z"),
    (("madrid",), "ES", "Madring",
     "M12 36 L20 18 L40 14 L48 24 L64 16 L86 20 L90 34 L72 40 L60 48 L40 46 L28 50 Z"),
    (("azerbaijan", "baku"), "AZ", "Baku City Circuit",
     "M10 50 L10 34 L22 34 L24 22 L34 20 L36 10 L48 10 L50 24 L88 22 L90 34 L70 40 L60 50 Z"),
    (("singapore", "marina bay"), "SG", "Marina Bay",
     "M12 16 L40 12 L44 22 L60 18 L84 20 L88 34 L74 36 L72 46 L52 50 L42 42 L26 46 L14 38 Z"),
    (("united states", "usa", "austin", "americas"), "US", "Circuit of the Americas",
     "M10 46 L18 14 L28 22 L40 16 L52 24 L66 18 L80 22 L90 34 L76 38 L62 46 L40 44 L26 50 Z"),
    (("mexic",), "MX", "Autódromo Hermanos Rodríguez",
     "M10 30 L20 16 L80 14 L90 20 L86 30 L70 30 L72 42 L54 46 L50 38 L30 40 L22 48 L12 42 Z"),
    (("brazil", "são paulo", "sao paulo", "interlagos"), "BR", "Interlagos",
     "M16 12 L50 14 L58 26 L80 22 L88 34 L74 46 L56 44 L46 50 L28 44 L34 32 L20 28 Z"),
    (("las vegas", "vegas"), "US", "Las Vegas Strip Circuit",
     "M10 44 L10 20 L28 16 L32 10 L44 12 L46 20 L88 18 L90 44 L60 46 L56 40 L40 40 L36 46 Z"),
    (("qatar", "lusail"), "QA", "Lusail International Circuit",
     "M12 36 C12 20 30 12 50 12 C72 12 90 20 88 32 L76 36 L70 44 L50 48 L42 42 L28 48 Z"),
    (("abu dhabi", "yas marina", "yas"), "AE", "Yas Marina",
     "M10 40 L16 16 L36 14 L42 24 L62 22 L68 12 L88 16 L86 30 L70 34 L64 44 L44 46 L30 42 L22 48 Z"),
    (("emilia", "imola"), "IT", "Imola",
     "M10 30 L24 14 L50 12 L70 18 L90 24 L84 36 L64 34 L56 44 L36 48 L20 44 Z"),
    (("portug", "portimão", "portimao", "algarve"), "PT", "Algarve International Circuit",
     "M12 44 L16 20 L30 12 L46 18 L62 12 L86 18 L88 32 L70 36 L66 46 L48 42 L30 50 Z"),
]

FLAGS = {"GB": "Great Britain"}


def flag_emoji(code):
    if not code or len(code) != 2:
        return ""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code.upper())


def lookup(name, location=""):
    text = f"{name} {location}".lower()
    for keys, code, circuit, path in CIRCUITS:
        if any(k in text for k in keys):
            return {"code": code, "flag": flag_emoji(code), "circuit": circuit, "path": path}
    return {"code": "", "flag": "", "circuit": location or "", "path": GENERIC}
