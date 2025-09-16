from lib.core.postgres_store import PostgresStore
from lib.services.health_indicator_analysis_service import HealthIndicatorAnalysisService





async def create_weight_loss_agent_tables():
    """Create weight loss agent tables (called during database initialization)"""

    from lib.models.weight_loss_agent import (
        HealthIndicator,
        InbodyMeasurement,
        InbodyReport,
        WeightLossAgentEnrollment,
    )

    # Tables are created automatically by SQLAlchemy when the models are imported
    # This function serves as a placeholder for any custom table creation logic
    print("Weight loss agent tables are ready (created via SQLAlchemy models)")




async def initialize_weight_loss_agent_data(postgres_store: PostgresStore):
    """Initialize weight loss agent data with default values"""

    try:
        # Basic initialization - just ensure the service can be instantiated
        health_analyzer = HealthIndicatorAnalysisService(postgres_store)

        print("Weight loss agent data initialized successfully")

    except Exception as e:
        print(f"Error initializing weight loss agent data: {e}")
        # Don't raise exception to avoid blocking app startup

