"""Zone components."""

from epinterface.document import EPDocument
from epinterface.sbem.common import NamedObject
from epinterface.sbem.components.envelope import ZoneEnvelopeComponent
from epinterface.sbem.components.operations import ZoneOperationsComponent


class ZoneComponent(NamedObject):
    """Zone definition."""

    Operations: ZoneOperationsComponent
    Envelope: ZoneEnvelopeComponent

    def add_to_idf_zone(self, doc: EPDocument, zone_name: str) -> EPDocument:
        """Add the zone to the IDF."""
        # TODO: consider lifting up the individual loads since the pass through method here
        # does not actually handle all of space use, given that it must synthesize
        # DHW and Operations.SpaceUse.WaterUse
        doc = self.Operations.SpaceUse.add_loads_to_idf_zone(doc, zone_name)
        doc = self.Operations.add_water_use_to_idf_zone(doc, zone_name)
        settings = self.Envelope.WindowSettings
        doc = self.Operations.add_conditioning_to_idf_zone(
            doc,
            zone_name,
            operable_fraction=1.0 if settings is None else settings.OperableArea,
        )
        doc = self.Envelope.Infiltration.add_infiltration_to_idf_zone(doc, zone_name)
        if settings is not None:
            doc = settings.add_shading_to_idf_zone(doc, zone_name)
        return doc
