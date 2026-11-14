"""Constants for Metron."""

DOMAIN = "metron"

DB_FILE = f"{DOMAIN}.db"
CARDS_URL = f"/{DOMAIN}/metron-cards.js"

# Where the data lives, chosen when adding the integration: an SQLite file in
# the config folder, or a Postgres database at CONF_DB_URL.
CONF_ENGINE = "engine"
CONF_DB_URL = "db_url"
ENGINE_SQLITE = "sqlite"
ENGINE_POSTGRESQL = "postgresql"

SUBENTRY_PERSON = "person"

# Person settings, stored in the person's sub-entry.
CONF_KEY = "key"
CONF_NAME = "name"
CONF_PERSON_ENTITY = "person_entity"
CONF_SEX = "sex"
CONF_BIRTH_DATE = "birth_date"
CONF_HEIGHT = "height_cm"
CONF_START_WEIGHT = "start_weight_kg"
CONF_START_DATE = "start_date"
CONF_GOAL_WEIGHT = "goal_weight_kg"
CONF_ACTIVITY = "activity"
CONF_PACE = "pace"
CONF_CALORIE_GOAL = "calorie_goal"
CONF_PROTEIN_PCT = "protein_pct"
CONF_CARBS_PCT = "carbs_pct"
CONF_FAT_PCT = "fat_pct"
CONF_ACTIVE_CALORIES_ENABLED = "active_calories_enabled"
CONF_ACTIVE_CALORIES_ENTITY = "active_calories_entity"
CONF_ACTIVE_CALORIES_SHARE = "active_calories_share"
CONF_ACTIVE_CALORIES_CAP = "active_calories_cap"

# Active calories settings for a new person, and for a person saved before
# these settings existed: off, 75% counted, at most 1,500 kcal counted a day,
# and no sensor, which has no key.
ACTIVE_CALORIES_DEFAULTS = {
    CONF_ACTIVE_CALORIES_ENABLED: False,
    CONF_ACTIVE_CALORIES_SHARE: 75,
    CONF_ACTIVE_CALORIES_CAP: 1500,
}

# The most kcal of activity one day can measure. A sensor reading more is a
# total that never resets.
MAX_ACTIVE_KCAL = 10_000

SEXES = ("female", "male")

MEALS = ("breakfast", "lunch", "dinner", "snacks")

# The weights a person can log, in kg, and the same in lb, rounded inwards
# to 0.1 lb.
MIN_KG = 20
MAX_KG = 400
MIN_LB = 44.1
MAX_LB = 881.8

# The heights a person can have, in cm.
MIN_CM = 100
MAX_CM = 250

# What a food or an entry can carry. The first four are required for foods;
# the rest are optional everywhere.
NUTRIENTS = ("kcal", "protein", "carbs", "fat", "fibre", "sugar", "saturated_fat", "salt")
REQUIRED_NUTRIENTS = NUTRIENTS[:4]

# Dispatcher signal sent after any write, with the person's key (None for
# changes to foods) and the set of ISO days whose entries changed.
SIGNAL_CHANGED = f"{DOMAIN}_changed"
# Sent, with nothing, each time the integration sets up: its people may have changed.
SIGNAL_PEOPLE = f"{DOMAIN}_people"

# The name of the entry that holds a day's calories imported from a sensor's
# history, which knows totals but not foods.
IMPORTED_ENTRY = "Imported total"
IMPORTED_MEAL = "snacks"

# The source recorded on entries imported from MyFitnessPal, which importing
# again replaces. Entries logged in Home Assistant have none.
SOURCE_MYFITNESSPAL = "myfitnesspal"
