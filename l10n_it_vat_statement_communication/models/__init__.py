# IMPORTANTE: Ordine di import corretto!
# Prima i modelli base, poi quelli che dipendono

from . import appointment_code
from . import config
from . import account
from . import comunicazione_liquidazione_vp  # Prima VP
from . import comunicazione_liquidazione     # Poi principale