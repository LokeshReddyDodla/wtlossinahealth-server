from datetime import date, datetime
from uuid import UUID

from celery import shared_task
from sqlalchemy.future import select
from sqlalchemy import update

from lib.dependencies.database import get_async_postgres_session
from lib.models.patient_package_assignment import (
    AssignmentStatus,
    PatientPackageAssignment,
)


@shared_task(queue="default")
async def update_package_assignment_statuses() -> None:
    try:
        async with get_async_postgres_session() as session:
            today = date.today()
            
            # Find all ACTIVE assignments that have passed their end_date
            stmt = select(PatientPackageAssignment).where(
                PatientPackageAssignment.status == AssignmentStatus.ACTIVE,
                PatientPackageAssignment.end_date < today,
            )
            
            result = await session.execute(stmt)
            expired_assignments = result.scalars().all()
            
            if not expired_assignments:
                print("ℹ️ No expired assignments to update")
                return
            
            # Update status to EXPIRED
            update_stmt = (
                update(PatientPackageAssignment)
                .where(
                    PatientPackageAssignment.status == AssignmentStatus.ACTIVE,
                    PatientPackageAssignment.end_date < today,
                )
                .values(
                    status=AssignmentStatus.EXPIRED,
                    updated_at=datetime.now().replace(tzinfo=None),
                )
            )
            
            await session.execute(update_stmt)
            await session.commit()
            
            print(
                f"✅ Updated {len(expired_assignments)} assignments to EXPIRED status"
            )
            
    except Exception as e:
        print(f"❌ Failed to update package assignment statuses: {e}")
        raise


@shared_task(queue="default")
async def update_assignment_status(
    assignment_id: str, new_status: str
) -> None:
    try:
        try:
            status_enum = AssignmentStatus(new_status.lower())
        except ValueError:
            print(f"❌ Invalid status: {new_status}")
            return
        
        async with get_async_postgres_session() as session:
            # Convert assignment_id to UUID
            try:
                assignment_uuid = UUID(assignment_id)
            except ValueError:
                print(f"❌ Invalid UUID format: {assignment_id}")
                return
            
            # Find the assignment
            stmt = select(PatientPackageAssignment).where(
                PatientPackageAssignment.assignment_id == assignment_uuid
            )
            result = await session.execute(stmt)
            assignment = result.scalar_one_or_none()
            
            if not assignment:
                print(f"⚠️ Assignment {assignment_id} not found")
                return
            
            # Update status
            assignment.status = status_enum
            assignment.updated_at = datetime.now().replace(tzinfo=None)
            
            await session.commit()
            
            print(
                f"✅ Updated assignment {assignment_id} to {status_enum.value} status"
            )
            
    except Exception as e:
        print(
            f"❌ Failed to update assignment {assignment_id} status: {e}"
        )
        raise

