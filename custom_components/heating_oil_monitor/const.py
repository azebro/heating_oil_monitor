DOMAIN = "heating_oil_monitor"

CONF_AIR_GAP_SENSOR = "air_gap_sensor"
CONF_TANK_DIAMETER = "tank_diameter_cm"
CONF_TANK_LENGTH = "tank_length_cm"
CONF_REFILL_THRESHOLD = "refill_threshold_liters"
CONF_NOISE_THRESHOLD = "noise_threshold_cm"
CONF_CONSUMPTION_DAYS = "consumption_calculation_days"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_REFERENCE_TEMPERATURE = "reference_temperature"

DEFAULT_REFILL_THRESHOLD = 100  # Liters
DEFAULT_NOISE_THRESHOLD = 2  # cm
DEFAULT_CONSUMPTION_DAYS = 7  # Days to average for consumption calculation
DEFAULT_REFERENCE_TEMPERATURE = 15.0  # °C - typical reference temperature for fuel

# Energy conversion constant for kerosene/heating oil
# Kerosene has approximately 10 kWh of energy per liter
KEROSENE_KWH_PER_LITER = 10.0

# Thermal expansion coefficient for kerosene/heating oil
# Volume change per degree Celsius (approximately 0.095% per °C)
THERMAL_EXPANSION_COEFFICIENT = 0.00095  # per °C
