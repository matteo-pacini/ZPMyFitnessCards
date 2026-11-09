"""Constants for ZPMyFitnessCards."""

DOMAIN = "zp_my_fitness"

DB_FILE = f"{DOMAIN}.db"
CARDS_URL = f"/{DOMAIN}/zp-my-fitness-cards.js"

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

SEXES = ("female", "male")

MEALS = ("breakfast", "lunch", "dinner", "snacks")

# What a food or an entry can carry. The first four are required for foods;
# the rest are optional everywhere.
NUTRIENTS = ("kcal", "protein", "carbs", "fat", "fibre", "sugar", "saturated_fat", "salt")
REQUIRED_NUTRIENTS = NUTRIENTS[:4]

# Dispatcher signal sent after any write, with the person's key (None for
# changes to foods) and the set of ISO days whose entries changed.
SIGNAL_CHANGED = f"{DOMAIN}_changed"

# The name of the entry that holds a day's calories imported from a sensor's
# history, which knows totals but not foods.
IMPORTED_ENTRY = "Imported total"
IMPORTED_MEAL = "snacks"
