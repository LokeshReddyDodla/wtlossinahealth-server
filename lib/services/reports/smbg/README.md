# SMBG Report Processor

Optimized and refactored SMBG statistics processor with improved maintainability, efficiency, and scalability.

## Structure

```
smbg/
├── __init__.py              # Package exports
├── processor.py             # Main processor (orchestrator)
├── constants.py             # Configuration constants
├── queries.py               # Database query utilities
├── statistics.py            # Statistics calculation utilities
├── meal_window_bucketer.py  # Meal window bucketing logic
└── README.md               # This file
```

## Architecture

### Separation of Concerns

The processor is now split into focused modules:

1. **`constants.py`**: Centralized configuration
   - Meal time windows
   - Glucose range thresholds
   - Meal type mappings
   - Bucket names

2. **`queries.py`**: Database operations
   - Single responsibility: data fetching
   - Reusable query methods
   - Optimized to reduce round trips

3. **`statistics.py`**: Statistical calculations
   - Pure functions for calculations
   - Reusable across different contexts
   - Well-tested logic

4. **`meal_window_bucketer.py`**: Meal window classification
   - Encapsulates bucketing logic
   - Handles overnight windows correctly
   - Easy to extend with new meal types

5. **`processor.py`**: Orchestration
   - Coordinates between modules
   - Business logic flow
   - Error handling

## Improvements

### 1. Code Organization
- **Before**: 315 lines in a single file
- **After**: Modular structure with focused responsibilities
- **Benefit**: Easier to test, maintain, and extend

### 2. Database Optimization
- **Before**: Multiple separate queries for previous week data
- **After**: Reusable query methods, optimized fetching
- **Benefit**: Reduced database round trips

### 3. Reusability
- **Before**: Logic embedded in methods
- **After**: Extracted utilities can be reused
- **Benefit**: DRY principle, consistent calculations

### 4. Maintainability
- **Before**: Hard-coded values scattered throughout
- **After**: Centralized constants
- **Benefit**: Easy to update thresholds and windows

### 5. Testability
- **Before**: Tightly coupled logic
- **After**: Pure functions and isolated modules
- **Benefit**: Unit testing is straightforward

### 6. Type Safety
- **Before**: Minimal type hints
- **After**: Comprehensive type annotations
- **Benefit**: Better IDE support, catch errors early

## Usage

```python
from lib.services.reports import SMBGStatsProcessor

processor = SMBGStatsProcessor(
    postgres_store=postgres_store,
    patient_profile_service=patient_profile_service,
    patient_plan_service=patient_plan_service,
    meal_stats_processor=meal_stats_processor,
)

# Get statistics for a date range
stats = await processor.get_stats(
    patient_id="patient-123",
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 1, 31),
)
```

## Key Features

### Meal Window Bucketing
- Automatically classifies readings into meal windows
- Handles overnight periods (e.g., dinner: 17:00-03:59)
- Supports pre-meal, post-meal, and random readings

### Statistics Calculation
- Basic stats: count, min, max, median, out-of-range
- Window-specific stats with average time
- Previous week comparisons
- Weekly trend analysis

### Monthly Summaries
- Pre-meal vs post-meal analysis
- Weekly trends within month
- Overall scores and percentages

## Performance Optimizations

1. **Single Query Fetching**: Reduced database queries by reusing query methods
2. **Efficient Filtering**: In-memory filtering after initial fetch
3. **Lazy Calculations**: Statistics calculated only when needed
4. **Batch Processing**: Process multiple windows in single pass

## Extensibility

### Adding New Meal Windows
Update `constants.py`:
```python
MEAL_WINDOWS = {
    "breakfast": (4, 11),
    "lunch": (11, 16),
    "dinner": (17, 3),
    "snack": (14, 16),  # New window
}
```

### Custom Statistics
Add methods to `statistics.py`:
```python
@staticmethod
def calculate_custom_stat(readings: List[PatientSMBG]) -> dict:
    # Custom calculation logic
    pass
```

## Testing

Each module can be tested independently:
- `queries.py`: Mock database sessions
- `statistics.py`: Pure function tests
- `meal_window_bucketer.py`: Input/output tests
- `processor.py`: Integration tests

## Future Enhancements

- [ ] Caching layer for frequently accessed data
- [ ] Async batch processing for large datasets
- [ ] Configurable glucose ranges per patient
- [ ] Advanced trend analysis (moving averages, etc.)
- [ ] Export to various formats (JSON, CSV, PDF)
