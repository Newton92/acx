from rest_framework import serializers
from .models import CollectionCase
from .serializers import (
    CollectionCaseSerializer,
    CollectionActionSerializer,
    PaymentPromiseSerializer,
    PaymentSerializer,
)


class CollectionCaseTimelineSerializer(serializers.Serializer):
    case = CollectionCaseSerializer()
    actions = CollectionActionSerializer(many=True)
    promises = PaymentPromiseSerializer(many=True)
    payments = PaymentSerializer(many=True)

    # Bonus "marché" (pratique pour UI)
    totals = serializers.DictField(child=serializers.CharField(), required=False)
