"""Base vector service class with common functionality."""

import logging
from abc import ABC
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from qdrant_client.models import PointIdsList, PointStruct

from lib.core.qdrant_store import QdrantStore
from lib.utils.vector_utils import embed_text_batch_safe

from .utils.constants import DEFAULT_CHUNK_SIZE, DEFAULT_COLLECTION_NAME
from .utils.exceptions import EmbeddingError, VectorServiceError
from .utils.payload_builder import PayloadBuilder
from .utils.point_id_generator import PointIdGenerator

logger = logging.getLogger(__name__)


class BaseVectorService(ABC):
    """Base class for all vector services with common functionality."""

    def __init__(
        self,
        qdrant_store: QdrantStore,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ):
        """
        Initialize base vector service.

        Args:
            qdrant_store: Qdrant store instance
            collection_name: Collection name for vector storage
        """
        self.qdrant_store = qdrant_store
        self.collection_name = collection_name
        self.payload_builder = PayloadBuilder()
        self.point_id_generator = PointIdGenerator()

    def _bucket_time(self, hour: int) -> str:
        """
        Map hour to time bucket.

        Args:
            hour: Hour of day (0-23)

        Returns:
            Time bucket name
        """
        return self.payload_builder.bucket_time(hour)

    def _time_buckets_for_range(
        self, start_time: datetime, end_time: datetime
    ) -> List[str]:
        """
        Calculate time buckets for a time range.

        Args:
            start_time: Start datetime
            end_time: End datetime

        Returns:
            List of time bucket names
        """
        return self.payload_builder.time_buckets_for_range(start_time, end_time)

    def _generate_point_id(
        self,
        patient_id: str,
        data_type: str,
        start_time: datetime,
        end_time: datetime,
        report_id: Optional[str] = None,
        additional_payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate a unique point ID.

        Args:
            patient_id: Patient identifier
            data_type: Data type identifier
            start_time: Start datetime
            end_time: End datetime
            report_id: Optional report identifier
            additional_payload: Optional payload for event-specific hashing

        Returns:
            MD5 hash string
        """
        return self.point_id_generator.generate(
            patient_id=patient_id,
            data_type=data_type,
            start_time=start_time,
            end_time=end_time,
            report_id=report_id,
            additional_payload=additional_payload,
        )

    def _generate_simple_point_id(self, entity_id: str) -> str:
        """
        Generate a simple point ID from entity ID.

        Args:
            entity_id: Entity identifier

        Returns:
            MD5 hash string
        """
        return self.point_id_generator.generate_simple(entity_id)

    def _extract_dates_from_report(
        self, report_data: Dict[str, Any], report_id: Optional[str] = None
    ) -> Tuple[datetime, datetime]:
        """
        Extract start and end dates from report metadata.date_range.

        Args:
            report_data: Report data dictionary
            report_id: Optional report ID for error messages

        Returns:
            Tuple of (start_time, end_time) as datetime objects

        Raises:
            ValueError: If metadata.date_range is missing or dates cannot be parsed
        """
        from lib.utils.datetime_utils import parse_datetime

        metadata = report_data.get("metadata", {})
        date_range = metadata.get("date_range", {})

        if not date_range:
            report_id_str = f" for report_id: {report_id}" if report_id else ""
            raise ValueError(
                f"Report data must contain 'metadata.date_range' structure{report_id_str}"
            )

        start_time = parse_datetime(date_range.get("start"))
        end_time = parse_datetime(date_range.get("end"))

        if not start_time or not end_time:
            report_id_str = f" for report_id: {report_id}" if report_id else ""
            raise ValueError(
                f"Failed to parse start_date or end_date from metadata.date_range{report_id_str}"
            )

        return start_time, end_time

    def _build_base_payload(
        self,
        patient_id: str,
        patient_age: int,
        patient_gender: str,
        data_type: str,
        text_repr: str,
        start_time: datetime,
        end_time: datetime,
        report_id: Optional[str] = None,
        additional_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build standardized base payload.

        Args:
            patient_id: Patient identifier
            patient_age: Patient age
            patient_gender: Patient gender
            data_type: Data type identifier
            text_repr: Text representation for embedding
            start_time: Start datetime
            end_time: End datetime
            report_id: Optional report identifier
            additional_payload: Optional additional payload fields

        Returns:
            Standardized payload dictionary
        """
        return self.payload_builder.build_base_payload(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            data_type=data_type,
            text_repr=text_repr,
            start_time=start_time,
            end_time=end_time,
            report_id=report_id,
            additional_payload=additional_payload,
        )

    async def _embed_texts_batch(
        self, texts: List[str]
    ) -> List[List[float]]:
        """
        Generate embeddings for a batch of texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors

        Raises:
            EmbeddingError: If embedding generation fails
        """
        try:
            if not texts:
                return []
            return await embed_text_batch_safe(texts)
        except Exception as e:
            raise EmbeddingError(
                f"Failed to generate embeddings: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def _batch_create_points(
        self,
        patient_id: str,
        patient_age: int,
        patient_gender: str,
        point_infos: List[Dict[str, Any]],
        report_id: Optional[str] = None,
    ) -> List[PointStruct]:
        """
        Create PointStruct objects from point info dictionaries.

        Args:
            patient_id: Patient identifier
            patient_age: Patient age
            patient_gender: Patient gender
            point_infos: List of point info dictionaries with:
                - data_type: str
                - text_repr: str
                - start_time: datetime
                - end_time: datetime
                - additional_payload: Optional[Dict[str, Any]]
            report_id: Optional report identifier

        Returns:
            List of PointStruct objects
        """
        if not point_infos:
            return []

        # Extract texts for batch embedding
        texts = [info["text_repr"] for info in point_infos]

        # Generate embeddings in batch
        embeddings = await self._embed_texts_batch(texts)

        # Create points
        points: List[PointStruct] = []
        for i, info in enumerate(point_infos):
            embedding = embeddings[i] if i < len(embeddings) else None

            if embedding is None:
                logger.warning(
                    f"Skipping point {i} due to missing embedding for "
                    f"data_type: {info.get('data_type')}"
                )
                continue

            # Build payload
            payload = self._build_base_payload(
                patient_id=patient_id,
                patient_age=patient_age,
                patient_gender=patient_gender,
                data_type=info["data_type"],
                text_repr=info["text_repr"],
                start_time=info["start_time"],
                end_time=info["end_time"],
                report_id=report_id,
                additional_payload=info.get("additional_payload"),
            )

            # Generate point ID
            point_id = self._generate_point_id(
                patient_id=patient_id,
                data_type=info["data_type"],
                start_time=info["start_time"],
                end_time=info["end_time"],
                report_id=report_id,
                additional_payload=info.get("additional_payload"),
            )

            points.append(
                PointStruct(id=point_id, vector=embedding, payload=payload)
            )

        return points

    async def upsert_points_batch(
        self,
        points: List[PointStruct],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        """
        Upsert points to Qdrant in batches.

        Args:
            points: List of PointStruct objects
            chunk_size: Size of chunks for batch processing

        Raises:
            VectorServiceError: If upsert fails
        """
        if not points:
            return

        try:
            await self.qdrant_store.upsert_points_chunked(
                self.collection_name, points, chunk_size
            )
            logger.info(
                f"✅ Upserted {len(points)} points to collection "
                f"'{self.collection_name}'"
            )
        except Exception as e:
            raise VectorServiceError(
                f"Failed to upsert points: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def delete_points_by_ids(
        self, point_ids: List[str]
    ) -> None:
        """
        Delete points by their IDs.

        Args:
            point_ids: List of point IDs to delete

        Raises:
            VectorServiceError: If deletion fails
        """
        if not point_ids:
            return

        try:
            async with self.qdrant_store.get_client() as client:
                await client.delete(
                    collection_name=self.collection_name,
                    points_selector=PointIdsList(points=point_ids),
                )
            logger.info(
                f"🗑️ Deleted {len(point_ids)} points from collection "
                f"'{self.collection_name}'"
            )
        except Exception as e:
            raise VectorServiceError(
                f"Failed to delete points: {e}",
                service_name=self.__class__.__name__,
            ) from e

    async def delete_points_by_filter(
        self,
        patient_id: str,
        data_type: Optional[str] = None,
    ) -> None:
        """
        Delete points by filter criteria.

        Args:
            patient_id: Patient identifier
            data_type: Optional data type filter

        Raises:
            VectorServiceError: If deletion fails
        """
        try:
            conditions = [
                FieldCondition(
                    key="patient_id", match=MatchValue(value=patient_id)
                )
            ]

            if data_type:
                conditions.append(
                    FieldCondition(
                        key="data_type", match=MatchValue(value=data_type)
                    )
                )

            async with self.qdrant_store.get_client() as client:
                await client.delete(
                    collection_name=self.collection_name,
                    points_selector=Filter(must=conditions),
                )

            filter_desc = (
                f"patient_id={patient_id}, data_type={data_type}"
                if data_type
                else f"patient_id={patient_id}"
            )
            logger.info(
                f"🧹 Deleted points matching {filter_desc} from collection "
                f"'{self.collection_name}'"
            )
        except Exception as e:
            raise VectorServiceError(
                f"Failed to delete points by filter: {e}",
                service_name=self.__class__.__name__,
            ) from e
