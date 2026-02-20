DOMAIN = "heating_oil_monitor"

CONF_AIR_GAP_SENSOR = "air_gap_sensor"
CONF_TANK_DIAMETER = "tank_diameter_cm"
CONF_TANK_LENGTH = "tank_length_cm"
CONF_REFILL_THRESHOLD = "refill_threshold_liters"
CONF_NOISE_THRESHOLD = "noise_threshold_liters"
CONF_CONSUMPTION_DAYS = "consumption_calculation_days"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_REFERENCE_TEMPERATURE = "reference_temperature"

DEFAULT_REFILL_THRESHOLD = 100  # Liters
DEFAULT_NOISE_THRESHOLD = 2  # Liters
DEFAULT_CONSUMPTION_DAYS = 7  # Days to average for consumption calculation
DEFAULT_REFERENCE_TEMPERATURE = 15.0  # °C - typical reference temperature for fuel

# History and persistence
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_history"
DEFAULT_CONSUMPTION_HISTORY_DAYS = 365
DEFAULT_REFILL_HISTORY_MAX = 50

# Refill stabilization settings
CONF_REFILL_STABILIZATION_MINUTES = "refill_stabilization_minutes"
CONF_REFILL_STABILITY_THRESHOLD = "refill_stability_threshold_liters"
DEFAULT_REFILL_STABILIZATION_MINUTES = (
    60  # Minutes to wait for readings to stabilize after refill
)
DEFAULT_REFILL_STABILITY_THRESHOLD = (
    5.0  # Liters - max variance to consider readings stable
)

# Reading filter settings (applies to all readings, not just refills)
CONF_READING_BUFFER_SIZE = "reading_buffer_size"
CONF_READING_DEBOUNCE_SECONDS = "reading_debounce_seconds"
DEFAULT_READING_BUFFER_SIZE = (
    5  # Number of readings to keep in buffer for median filter
)
DEFAULT_READING_DEBOUNCE_SECONDS = 60  # Minimum seconds between processing readings

# Energy conversion constant for kerosene/heating oil
# Kerosene has approximately 10 kWh of energy per liter
KEROSENE_KWH_PER_LITER = 10.0

# Thermal expansion coefficient for kerosene/heating oil
# Volume change per degree Celsius (approximately 0.095% per °C)
THERMAL_EXPANSION_COEFFICIENT = 0.00095  # per °C
