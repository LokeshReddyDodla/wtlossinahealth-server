# Patient Profile Vector Point Structure

This document describes the structure of Patient Profile data points stored in the Qdrant vector database.

## Overview

Patient Profile points represent static patient demographic and health information, including medical history, lifestyle habits, and personal attributes.

## Base Payload Structure

**Note**: Profile points are unique - they don't have time-based fields like `start_time`, `end_time`, `date`, `day_of_week`, `is_weekend`, `week_number`, `month`, or `time_of_day_bucket` since they represent static patient information rather than time-based events.

```json
{
  "data_type": "profile",
  "patient_id": "uuid-string",
  "text_repr": "name: John Doe | age: 45 | gender: male | ..."
}
```

## Data Type

- `profile` - Patient profile information

## Example: Patient Profile Point

```json
{
  "id": "j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5",
  "vector": [0.012, -0.345, 0.678, ...],
  "payload": {
    "data_type": "profile",
    "patient_id": "550e8400-e29b-41d4-a716-446655440000",
    "text_repr": "name: John Doe | age: 45 | gender: male | height_cm: 175 | weight_kg: 80 | waist_cm: 90 | bmi: 26.1 | activity_level: moderate | diet_preference: low-carb | cuisines: indian, mediterranean | meals_per_day: 3 | snacks_count: 2 | meal_timings: breakfast, lunch, dinner | food_allergies: peanuts, shellfish | drug_allergies: penicillin | alcohol_consumption: True | alcohol_types: beer, wine | smoking_habit: False | years_of_smoking: 0 | cigarettes_per_day: 0 | quit_years_ago: 5 | wake_up_fresh: True | drowsy_day: False | sleep_quality: good | diabetes_type: type_2 | years_with_diabetes: 5 | is_pregnant: False | family_history: father (10 yrs), mother (8 yrs) | medical_history: hypertension (3 yrs), obesity (5 yrs)",
    "first_name": "John",
    "last_name": "Doe",
    "age": 45,
    "gender": "male",
    "height": 175,
    "weight": 80,
    "waist": 90,
    "bmi": 26.1,
    "activity_level": "moderate",
    "food_allergies": ["peanuts", "shellfish"],
    "drug_allergies": ["penicillin"],
    "alcohol_consumption": true,
    "alcohol_consumption_frequency": "weekly",
    "alcohol_consumption_quantity": "2-3 drinks",
    "alcohol_consumption_types": ["beer", "wine"],
    "smoking_habit": false,
    "years_of_smoking": 0,
    "cigarettes_per_day": 0,
    "quit_years_ago": 5,
    "snacks_count": 2,
    "meals_per_day": 3,
    "meal_timings": ["breakfast", "lunch", "dinner"],
    "cuisine_preferences": ["indian", "mediterranean"],
    "diet_preference": "low-carb",
    "sleep_quality": "good",
    "wake_up_fresh": true,
    "drowsy_day": false,
    "average_sleep_duration": "7-8 hours",
    "wake_up_time": "06:30",
    "bed_time": "22:30",
    "type_of_diabetes": "type_2",
    "years_with_diabetes": 5,
    "is_pregnant": false,
    "pregnancy_weeks": 0,
    "family_diabetic_members": ["father", "mother"],
    "family_diabetic_years": [10, 8],
    "medical_conditions": ["hypertension", "obesity"],
    "medical_conditions_years": [3, 5],
    "medical_conditions_details": ["controlled with medication", "BMI 26.1"]
  }
}
```

## Field Descriptions

### Demographics

- **first_name**: Patient's first name
- **last_name**: Patient's last name
- **age**: Patient age in years
- **gender**: Patient gender ("male", "female", "other")
- **height**: Height in cm
- **weight**: Weight in kg
- **waist**: Waist circumference in cm
- **bmi**: Body Mass Index (calculated)

### Activity & Lifestyle

- **activity_level**: Activity level (e.g., "sedentary", "moderate", "active")
- **diet_preference**: Dietary preference (e.g., "low-carb", "vegetarian")
- **cuisine_preferences**: Array of preferred cuisines
- **meals_per_day**: Number of meals per day
- **snacks_count**: Number of snacks per day
- **meal_timings**: Array of meal timing types

### Allergies

- **food_allergies**: Array of food allergy names
- **drug_allergies**: Array of drug allergy names

### Alcohol Consumption

- **alcohol_consumption**: Boolean
- **alcohol_consumption_frequency**: Frequency (e.g., "daily", "weekly")
- **alcohol_consumption_quantity**: Quantity description
- **alcohol_consumption_types**: Array of alcohol types consumed

### Smoking Habits

- **smoking_habit**: Boolean indicating current smoking status
- **years_of_smoking**: Years of smoking (if applicable)
- **cigarettes_per_day**: Cigarettes per day (if applicable)
- **quit_years_ago**: Years since quitting (if applicable)

### Sleep Habits

- **sleep_quality**: Sleep quality description
- **wake_up_fresh**: Boolean
- **drowsy_day**: Boolean
- **average_sleep_duration**: Average sleep duration
- **wake_up_time**: Typical wake-up time
- **bed_time**: Typical bedtime

### Diabetes History

- **type_of_diabetes**: Type of diabetes (e.g., "type_1", "type_2")
- **years_with_diabetes**: Years since diagnosis
- **is_pregnant**: Boolean (for gestational diabetes)
- **pregnancy_weeks**: Weeks of pregnancy (if applicable)

### Family History

- **family_diabetic_members**: Array of family members with diabetes
- **family_diabetic_years**: Array of years each family member has had diabetes

### Medical Conditions

- **medical_conditions**: Array of medical condition names
- **medical_conditions_years**: Array of years for each condition
- **medical_conditions_details**: Array of details for each condition

## Text Representation

The text representation is a pipe-separated format containing all profile information in a structured, searchable format for embedding.

## Point ID Generation

Profile point IDs are generated using MD5 hashing:

- **Profile**: `MD5(patient_id)`

The patient_id is hashed directly to create a unique identifier for each patient profile.
