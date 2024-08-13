from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# Import all models to ensure they are registered with the base
from lib.models.patient import *
from lib.models.patient_connected_app import *
from lib.models.patient_permission import *
from lib.models.patient_vitals import *
from lib.models.patient_smbg import *
from lib.models.patient_sleep import *
from lib.models.meal import *
from lib.models.admin import *
from lib.models.fitness_data_sync import *