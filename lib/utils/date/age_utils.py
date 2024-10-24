from datetime import datetime


def calculate_age(dob: datetime) -> int:
    """Calculate age from date of birth."""
    today = datetime.today()
    return (
        today.year
        - dob.year
        - ((today.month, today.day) < (dob.month, dob.day))
    )
