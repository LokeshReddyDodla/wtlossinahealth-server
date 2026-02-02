# Vector Services Documentation

This directory contains all vector services for storing patient data in the Qdrant vector database.

## Overview

Each vector service processes domain-specific data and stores it as vector embeddings for semantic search and retrieval.

## Services

- **[CGM Service](cgm/structure.md)** - Continuous Glucose Monitoring data
- **[Fitness Service](fitness/structure.md)** - Physical activity and fitness data
- **[Meal Service](meal/structure.md)** - Meal and nutrition data
- **[SMBG Service](smbg/structure.md)** - Self-Monitoring Blood Glucose readings
- **[Profile Service](profile/structure.md)** - Patient profile and demographic data
- **[Vitals Service](vitals/structure.md)** - Patient vital signs (blood pressure, heart rate, temperature, etc.)

## Base Structure

All vector points share a common base structure. See the [Base Vector Service](base.py) for implementation details.

### Common Payload Fields

All time-based points include:
- `patient_id` - Patient UUID
- `patient_age` - Patient age
- `patient_gender` - Patient gender
- `data_type` - Type of data point
- `text_repr` - Text representation for embedding
- `start_time` - Start timestamp (milliseconds)
- `end_time` - End timestamp (milliseconds)
- `date` - ISO date string
- `day_of_week` - 0-6 (Monday=0)
- `is_weekend` - Boolean
- `week_number` - ISO week number
- `month` - Month number (1-12)
- `time_of_day_bucket` - Array of time buckets

## Vector Embedding

- **Model**: `text-embedding-3-large`
- **Dimensions**: 3072
- **Distance Metric**: Cosine similarity
- **Collection**: `patient_data` (default)

## Point Structure Documentation

Each service has its own structure documentation file:

- [CGM Point Structure](cgm/structure.md)
- [Fitness Point Structure](fitness/structure.md)
- [Meal Point Structure](meal/structure.md)
- [SMBG Point Structure](smbg/structure.md)
- [Profile Point Structure](profile/structure.md)
- [Vitals Point Structure](vitals/structure.md)

## Architecture

```
vector/
├── base.py              # BaseVectorService - common functionality
├── cgm/                 # CGM vector service
│   ├── service.py
│   ├── processor.py
│   ├── templates.py
│   ├── configs.py
│   └── structure.md     # CGM point structure docs
├── fitness/             # Fitness vector service
│   ├── service.py
│   ├── processor.py
│   ├── templates.py
│   ├── configs.py
│   └── structure.md     # Fitness point structure docs
├── meal/                # Meal vector service
│   ├── service.py
│   ├── text_builder.py
│   └── structure.md     # Meal point structure docs
├── smbg/                # SMBG vector service
│   ├── service.py
│   ├── text_builder.py
│   └── structure.md     # SMBG point structure docs
├── profile/             # Profile vector service
│   ├── service.py
│   ├── text_builder.py
│   └── structure.md     # Profile point structure docs
├── vitals/              # Vitals vector service
│   ├── service.py
│   ├── text_builder.py
│   └── structure.md     # Vitals point structure docs
└── utils/               # Shared utilities
    ├── constants.py
    ├── payload_builder.py
    ├── point_id_generator.py
    └── exceptions.py
```

## Usage

All services inherit from `BaseVectorService` and follow consistent patterns:

```python
from lib.services.vector import CGMVectorService, FitnessVectorService

# Services are registered in the dependency injection container
# and can be resolved via service dependencies
```

## Point ID Generation

Point IDs are generated using MD5 hashing with service-specific strategies. See individual service documentation for details.
