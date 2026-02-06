# Meal Vector Point Structure

This document describes the structure of Meal data points stored in the Qdrant vector database.

## Overview

Meal points represent individual meal entries with nutritional information, food items, and meal metadata.

## Base Payload Structure

All Meal points include these common fields:

```json
{
  "patient_id": "uuid-string",
  "patient_age": 45,
  "patient_gender": "male",
  "data_type": "meal",
  "text_repr": "Grilled Chicken Salad (lunch) meal. ...",
  "start_time": 1705324200000,
  "end_time": 1705324200000,
  "date": "2024-01-15",
  "day_of_week": 0,
  "is_weekend": false,
  "week_number": 3,
  "month": 1,
  "time_of_day_bucket": ["afternoon"]
}
```

## Data Type

- `meal` - Individual meal entry

## Example: Meal Point

```json
{
  "id": "h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3",
  "vector": [0.890, -0.123, 0.456, ...],
  "payload": {
    "patient_id": "550e8400-e29b-41d4-a716-446655440000",
    "patient_age": 45,
    "patient_gender": "male",
    "data_type": "meal",
    "text_repr": "Grilled Chicken Salad (lunch) meal. Description: Healthy lunch option. Tags: healthy, low-carb. Eaten on 2024-01-15 at 13:30. Macronutrients: calories: 450, proteins: 35, carbohydrates: 25, fats: 20. Micronutrients: fiber: 8, calcium: 150, iron: 3.5. Grilled Chicken (150 g) Serving size: 1 serving. Macronutrients: calories: 250, proteins: 30, carbohydrates: 0, fats: 12. Micronutrients: iron: 2.0, zinc: 3.0. Mixed Greens (100 g) Serving size: 1 cup. Macronutrients: calories: 20, proteins: 2, carbohydrates: 3, fats: 0. Micronutrients: calcium: 50, iron: 1.5. Overall health profile: high protein, low carb, high fiber. This lunch (Grilled Chicken Salad) is high protein, low carb, high fiber.",
    "start_time": 1705324200000,
    "end_time": 1705324200000,
    "date": "2024-01-15",
    "day_of_week": 0,
    "is_weekend": false,
    "week_number": 3,
    "month": 1,
    "time_of_day_bucket": ["afternoon"],
    "meal_id": "meal_789",
    "meal_name": "Grilled Chicken Salad",
    "meal_type": "lunch",
    "meal_date": "2024-01-15",
    "meal_time": "13:30",
    "image_url": "https://example.com/meal_image.jpg",
    "description": "Healthy lunch option",
    "analyzed": true,
    "tags": ["healthy", "low-carb"],
    "uploaded_at": 1705324500000,
    "nutrition": {
      "calories": 450,
      "proteins": 35,
      "carbohydrates": 25,
      "fats": 20,
      "fiber": 8,
      "calcium": 150,
      "iron": 3.5
    },
    "items": [
      {
        "item_name": "Grilled Chicken",
        "serving_quantity": 150,
        "serving_unit": "g",
        "serving_size": "1 serving",
        "macro_nutritional_values": {
          "calories": 250,
          "proteins": 30,
          "carbohydrates": 0,
          "fats": 12
        },
        "micro_nutritional_values": {
          "iron": 2.0,
          "zinc": 3.0
        }
      },
      {
        "item_name": "Mixed Greens",
        "serving_quantity": 100,
        "serving_unit": "g",
        "serving_size": "1 cup",
        "macro_nutritional_values": {
          "calories": 20,
          "proteins": 2,
          "carbohydrates": 3,
          "fats": 0
        },
        "micro_nutritional_values": {
          "calcium": 50,
          "iron": 1.5
        }
      }
    ]
  }
}
```

## Field Descriptions

### Meal-Specific Fields

- **meal_id**: Unique meal identifier
- **meal_name**: Name of the meal
- **meal_type**: Type of meal (breakfast, lunch, dinner, snack)
- **meal_date**: Date of meal (YYYY-MM-DD)
- **meal_time**: Time of meal (HH:MM)
- **image_url**: URL to meal image (if available)
- **description**: Meal description
- **analyzed**: Boolean indicating if meal was analyzed
- **tags**: Array of meal tags (e.g., ["healthy", "low-carb"])
- **uploaded_at**: Timestamp when meal was uploaded (milliseconds)

### Nutrition Fields

- **nutrition**: Object containing total nutritional values
  - **calories**: Total calories
  - **proteins**: Protein in grams
  - **carbohydrates**: Carbs in grams
  - **fats**: Fats in grams
  - **fiber**: Fiber in grams
  - **calcium**: Calcium in mg
  - **iron**: Iron in mg
  - (and other micronutrients)

### Food Items

- **items**: Array of individual food items in the meal
  - **item_name**: Name of food item
  - **serving_quantity**: Quantity of serving
  - **serving_unit**: Unit of measurement (g, ml, etc.)
  - **serving_size**: Size description
  - **macro_nutritional_values**: Macronutrients for this item
  - **micro_nutritional_values**: Micronutrients for this item

## Point ID Generation

Meal point IDs are generated using MD5 hashing:

- **Meal**: `MD5(meal_id)`

The meal_id is hashed directly to create a unique identifier for each meal entry.
