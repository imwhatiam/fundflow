from rest_framework import serializers

from fundflow.models import Sector


class SectorSerializer(serializers.ModelSerializer):
    constituent_count = serializers.IntegerField(source="constituents.count", read_only=True)

    class Meta:
        model = Sector
        fields = ["code", "name", "category", "constituent_count", "updated_at"]
