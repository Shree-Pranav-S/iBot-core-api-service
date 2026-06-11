"""
Base Pydantic schema configuration.

All IBot schemas inherit from one of these base classes so that
common config (from_attributes, populate_by_name, etc.) is set
in one place.
"""

from pydantic import BaseModel, ConfigDict


class AppBaseModel(BaseModel):
    """
    Base for all request / plain-object schemas.
    Forbids extra fields so unknown payload keys surface as validation errors.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class ORMBaseModel(BaseModel):
    """
    Base for all response schemas that are constructed from ORM objects.
    Enables from_attributes mode (previously orm_mode) so SQLAlchemy
    model instances can be passed directly to model_validate().
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )
