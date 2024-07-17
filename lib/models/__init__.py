from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# Import all models to ensure they are registered with the base
from lib.models.patient import *
from lib.models.meal import *
    