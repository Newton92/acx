from rest_framework import serializers

class SessionSerializer(serializers.Serializer):
    """
    Représentation d'une "session" basée sur OutstandingToken (refresh tokens).
    L'id côté front = jti.
    """
    id = serializers.CharField()
    ip = serializers.CharField(required=False, allow_null=True)
    user_agent = serializers.CharField(required=False, allow_null=True)
    last_seen = serializers.DateTimeField(required=False, allow_null=True)