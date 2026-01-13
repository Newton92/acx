# accounts/jwt_views.py
from rest_framework_simplejwt.views import TokenObtainPairView
from .jwt_serializers import EmailOrUsernameTokenObtainPairSerializer


class EmailOrUsernameTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailOrUsernameTokenObtainPairSerializer
