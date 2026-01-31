from rest_framework import serializers

from .serializers import (
    CollectionCaseSerializer,
    CollectionActionSerializer,
    PaymentPromiseSerializer,
    PaymentSerializer,
)


class CollectionCaseTimelineSerializer(serializers.Serializer):
    """
    Timeline "marché" : un seul payload pour alimenter l'onglet Recouvrement.

    - case : dossier de recouvrement
    - actions : actions (appel/sms/email/visite/notice/lawyer/etc.)
      *inclut details_json si details contient du JSON*
    - promises : promesses de paiement (inclut notes_json si notes contient du JSON)
    - payments : paiements (inclut notes_json si notes contient du JSON)
    - totals : agrégats déjà calculés côté view (strings) pour UI
    """

    case = CollectionCaseSerializer()
    actions = CollectionActionSerializer(many=True)
    promises = PaymentPromiseSerializer(many=True)
    payments = PaymentSerializer(many=True)

    # Bonus "marché" (pratique pour UI)
    totals = serializers.DictField(child=serializers.CharField(), required=False)
